"""REQ-8-04 — PATCH /pesquisas/{uuid}/keywords/bulk-intel.

Bulk UPDATE com error accumulation. Nunca retorna 500 global — sempre 200
com `{updated, not_found, invalid}`. Vocabulário difficulty_label canônico
(D-04): 'LOW', 'MED', 'HIGH' — outros valores vão para invalid[].

Estratégia: seed pesquisa + kw_staging pending, chama endpoint,
valida efeito via SELECT, cleanup no teardown.

## Fase 35 / D-02 — a pesquisa e as keywords vivem em bancos diferentes
`pesquisas` continua no Postgres da Stack (`pg_conn`); `kw_staging` mora no Supabase,
schema `leadgen` (`db_conn`). Todo seed, teardown e asserção de estado usa a conexão do
banco certo. O reset do pool do Supabase vem da fixture autouse do `conftest.py`.

Pré-condições:
- Túnel VPS Postgres em localhost:5433 (`bash vps_tunnel.sh -d`).
- `LEADGEN_DB_URL` no `.env` apontando para o Supavisor session pooler.
- Migration 017 aplicada (colunas competitive_score/difficulty_label/intel_json em kw_staging).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_bulk_intel.py -v
"""

import os
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from main import app  # noqa: E402
import db as db_module  # noqa: E402
import db_leadgen as lg_module  # noqa: E402


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Fecha o pool antes/depois de cada teste (mesmo padrão dos outros testes)."""
    if db_module._pool is not None:
        try:
            await db_module._pool.close()
        except Exception:
            pass
        db_module._pool = None
    yield
    if db_module._pool is not None:
        try:
            await db_module._pool.close()
        except Exception:
            pass
        db_module._pool = None


@pytest.fixture
async def db_conn():
    """Supabase, schema `leadgen` — é onde `kw_staging` mora desde a Fase 35."""
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"},
    )
    yield conn
    await conn.close()


@pytest.fixture
async def pg_conn():
    """Postgres da Stack — `pesquisas` é camada de decisão e não migrou."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


async def _seed(pg_conn, lg_conn, n=3):
    """Cria pesquisa (Postgres) + n kw_staging pending (Supabase).

    Retorna (pesquisa_id_str, [kw_id_int, ...]).
    """
    suffix = uuid.uuid4().hex[:8]
    pid = await pg_conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel)
           VALUES ($1, $2, 'Brasília', 'classificado', 'principal') RETURNING id""",
        f"Test-Bulk-Intel-{suffix}", f"nicho-bulk-{suffix}",
    )
    kw_ids = []
    if n:
        # Um único INSERT para as n keywords: com o banco do outro lado da internet, um
        # INSERT por linha faria o seed de 200 itens levar mais tempo que o próprio teste.
        rows = await lg_conn.fetch(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               SELECT $1::uuid, k, 'PAGINA_PRINCIPAL', 'pending'
                 FROM unnest($2::text[]) AS k
               RETURNING id""",
            str(pid), [f"kw-bulk-{suffix}-{i}" for i in range(n)],
        )
        kw_ids = [r["id"] for r in rows]
    return str(pid), kw_ids


async def _cleanup(pg_conn, lg_conn, pesquisa_id):
    await lg_conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id)
    await pg_conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


@pytest.mark.asyncio
async def test_bulk_intel_happy(db_conn, pg_conn):
    """T1: 3 items válidos → updated=3, not_found=[], invalid=[]."""
    pid, kw_ids = await _seed(pg_conn, db_conn, n=3)
    try:
        payload = {"items": [
            {"keyword_id": k, "competitive_score": 50.0, "difficulty_label": "MED",
             "top_competitor_url": "https://x.com/a", "intel_json": {"x": 1}}
            for k in kw_ids
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 3
        assert body["not_found"] == []
        assert body["invalid"] == []
        rows = await db_conn.fetch(
            "SELECT id, competitive_score, difficulty_label, top_competitor_url FROM kw_staging WHERE id = ANY($1::int[])",
            kw_ids,
        )
        for row in rows:
            assert row["competitive_score"] == 50.0
            assert row["difficulty_label"] == "MED"
            assert row["top_competitor_url"] == "https://x.com/a"
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_error_accumulation(db_conn, pg_conn):
    """T2 (CRIT-8): 2 válidos + 2 IDs inexistentes + 1 label inválido → 200 com relatório."""
    pid, kw_ids = await _seed(pg_conn, db_conn, n=2)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "competitive_score": 50.0, "difficulty_label": "MED", "intel_json": {}},
            {"keyword_id": kw_ids[1], "competitive_score": 60.0, "difficulty_label": "LOW", "intel_json": {}},
            {"keyword_id": 99999999, "competitive_score": 30.0, "difficulty_label": "HIGH", "intel_json": {}},
            {"keyword_id": 99999998, "competitive_score": 40.0, "difficulty_label": "LOW", "intel_json": {}},
            {"keyword_id": kw_ids[0], "competitive_score": 50.0, "difficulty_label": "baixo", "intel_json": {}},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == 2, body
        assert sorted(body["not_found"]) == [99999998, 99999999], body
        assert len(body["invalid"]) == 1, body
        assert body["invalid"][0]["id"] == kw_ids[0]
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_difficulty_label_lowercase_invalid(db_conn, pg_conn):
    """T3 (D-04): 'baixo'/'médio'/'alto' → invalid[], sem UPDATE."""
    pid, kw_ids = await _seed(pg_conn, db_conn, n=1)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "competitive_score": 50.0, "difficulty_label": "baixo", "intel_json": {}},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == 0
        assert len(body["invalid"]) == 1
        assert body["invalid"][0]["id"] == kw_ids[0]
        assert "difficulty_label" in body["invalid"][0]["reason"].lower()
        # Confirma no banco: nada foi atualizado
        row = await db_conn.fetchrow("SELECT difficulty_label FROM kw_staging WHERE id = $1", kw_ids[0])
        assert row["difficulty_label"] is None
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_score_out_of_range(db_conn, pg_conn):
    """T4: competitive_score=150 → invalid[]."""
    pid, kw_ids = await _seed(pg_conn, db_conn, n=1)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "competitive_score": 150.0, "difficulty_label": "MED", "intel_json": {}},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == 0
        assert len(body["invalid"]) == 1
        assert "score" in body["invalid"][0]["reason"].lower() or "0" in body["invalid"][0]["reason"]
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_empty_payload(db_conn, pg_conn):
    """T5: {items: []} → {updated: 0, not_found: [], invalid: []} (200)."""
    pid, _ = await _seed(pg_conn, db_conn, n=0)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json={"items": []})
        assert r.status_code == 200
        assert r.json() == {"updated": 0, "not_found": [], "invalid": []}
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_pesquisa_404():
    """T6: UUID randômico → 404 pt-BR."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(f"/pesquisas/{fake}/keywords/bulk-intel", json={"items": []})
    assert r.status_code == 404
    assert "Pesquisa" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bulk_intel_idempotent(db_conn, pg_conn):
    """T7: rerun idêntico → mesmo updated=3 (UPDATE não-destrutivo)."""
    pid, kw_ids = await _seed(pg_conn, db_conn, n=3)
    try:
        payload = {"items": [
            {"keyword_id": k, "competitive_score": 50.0, "difficulty_label": "MED", "intel_json": {"x": 1}}
            for k in kw_ids
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
            r2 = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["updated"] == 3
        assert r2.json()["updated"] == 3
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_all_canonical_labels(db_conn, pg_conn):
    """T8: LOW, MED, HIGH todos aceitos."""
    pid, kw_ids = await _seed(pg_conn, db_conn, n=3)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "competitive_score": 20.0, "difficulty_label": "LOW", "intel_json": {}},
            {"keyword_id": kw_ids[1], "competitive_score": 50.0, "difficulty_label": "MED", "intel_json": {}},
            {"keyword_id": kw_ids[2], "competitive_score": 80.0, "difficulty_label": "HIGH", "intel_json": {}},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == 3
        assert body["invalid"] == []
        rows = await db_conn.fetch(
            "SELECT difficulty_label FROM kw_staging WHERE id = ANY($1::int[]) ORDER BY id",
            kw_ids,
        )
        labels = {r["difficulty_label"] for r in rows}
        assert labels == {"LOW", "MED", "HIGH"}
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_lote_grande_em_uma_ida(db_conn, pg_conn):
    """T9 (Fase 35): lote de 200 itens → updated=200 e tempo de parede < 5 s.

    O limite de tempo é a asserção que importa: o laço item a item que existia antes
    fazia um round-trip por keyword. Contra o Supabase (internet pública, TLS) 200 idas
    não cabem em 5 s — só a instrução única em lote cabe.

    Os pools são aquecidos ANTES de começar a contar: a fixture autouse do conftest fecha
    o pool do Supabase a cada teste, e o handshake TLS de abertura (~3 s) mascararia o que
    a asserção quer medir, que é o custo do lote em si.
    """
    n = 200
    pid, kw_ids = await _seed(pg_conn, db_conn, n=n)
    assert len(kw_ids) == n, f"seed devolveu {len(kw_ids)} ids"
    try:
        payload = {"items": [
            {"keyword_id": k, "competitive_score": 42.0, "difficulty_label": "HIGH",
             "top_competitor_url": f"https://x.com/{k}", "intel_json": {"pos": i}}
            for i, k in enumerate(kw_ids)
        ]}
        await (await db_module.get_pool()).fetchval("SELECT 1")
        await (await lg_module.get_lg_pool()).fetchval("SELECT 1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            inicio = time.perf_counter()
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
            decorrido = time.perf_counter() - inicio

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == n, body
        assert body["not_found"] == []
        assert body["invalid"] == []
        assert decorrido < 5.0, f"lote de {n} levou {decorrido:.2f}s — laço item a item?"

        # O efeito é real no banco, não só na resposta.
        gravadas = await db_conn.fetchval(
            """SELECT count(*) FROM kw_staging
                WHERE id = ANY($1::int[]) AND difficulty_label = 'HIGH'
                  AND competitive_score = 42.0 AND intel_updated_at IS NOT NULL""",
            kw_ids,
        )
        assert gravadas == n
    finally:
        await _cleanup(pg_conn, db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_grava_intel_json_como_objeto(db_conn, pg_conn):
    """T10: `intel_json` é gravado como objeto JSONB, não como texto JSON.

    Regressão: o handler serializava com `json.dumps` **e** o codec JSONB do pool
    aplicava `json.dumps` de novo, gravando `"{\\"x\\": 1}"` (jsonb_typeof='string')
    em vez do objeto. Quem lesse a coluna recebia uma string e o spread quebrava.
    """
    pid, kw_ids = await _seed(pg_conn, db_conn, n=1)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "competitive_score": 10.0,
             "difficulty_label": "LOW", "intel_json": {"regioes": ["df"], "n": 3}},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 1

        row = await db_conn.fetchrow(
            """SELECT jsonb_typeof(intel_json) AS tipo,
                      intel_json->>'n'        AS n
                 FROM kw_staging WHERE id = $1""",
            kw_ids[0],
        )
        assert row["tipo"] == "object", f"intel_json gravado como {row['tipo']}"
        assert row["n"] == "3"
    finally:
        await _cleanup(pg_conn, db_conn, pid)
