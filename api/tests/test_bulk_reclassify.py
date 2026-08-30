"""KWMGMT-01 — PATCH /pesquisas/{uuid}/keywords/bulk-reclassify.

Bulk UPDATE de kw_type em kw_staging com error accumulation.
Nunca retorna 500 global — sempre 200 com `{updated, not_found, invalid}`.
Tipos aceitos: PAGINA_PRINCIPAL, PAGINA_GEO, LOCALIDADE, SECAO, SURPRESA, DESCARTA, SERVICO.

## Fase 35 / D-02 — a suíte fala com DOIS bancos
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

  `pg_conn` → Postgres da Stack: `pesquisas` (camada de decisão, não migrou).
  `lg_conn` → Supabase, schema `leadgen`: `kw_staging` (camada pré-decisão).

Seed e asserções de `kw_staging` vão para o Supabase; se fossem para o Postgres, o teste
passaria sem provar nada — as tabelas ainda existem nos dois bancos até o Plan 11.

Pré-condições:
- Túnel VPS Postgres em localhost:5433 (`bash vps_tunnel.sh -d`).
- `LEADGEN_DB_URL` no `.env` apontando para o Supavisor session pooler.
- AUTH_ENABLED=false (o conftest já resolve as três coisas).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_bulk_reclassify.py -v
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


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Fecha o pool antes/depois de cada teste (mesmo padrão dos outros testes).

    O pool do Supabase (`db_leadgen._lg_pool`) é zerado pela fixture autouse do
    `conftest.py` — não precisa ser duplicada aqui.
    """
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
async def pg_conn():
    """Postgres da Stack — `pesquisas` é camada de decisão e não migrou."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


@pytest.fixture
async def lg_conn():
    """Supabase, schema `leadgen` — onde `kw_staging` mora desde a Fase 35."""
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"},
    )
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
        f"Test-Bulk-Reclassify-{suffix}", f"nicho-reclassify-{suffix}",
    )
    # Um único INSERT ... SELECT: com o banco do outro lado da internet, n inserts
    # item a item tornariam o próprio seed o gargalo do teste de lote grande.
    rows = await lg_conn.fetch(
        """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
           SELECT $1::uuid, $2 || i::text, 'PAGINA_PRINCIPAL', 'pending'
             FROM generate_series(0, $3::int - 1) AS g(i)
           RETURNING id""",
        pid, f"kw-reclassify-{suffix}-", n,
    )
    return str(pid), [r["id"] for r in rows]


async def _cleanup(pg_conn, lg_conn, pesquisa_id):
    await lg_conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id)
    await pg_conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


@pytest.mark.asyncio
async def test_bulk_reclassify_happy(pg_conn, lg_conn):
    """T1: 3 items válidos → updated=3, not_found=[], invalid=[]."""
    pid, kw_ids = await _seed(pg_conn, lg_conn, n=3)
    try:
        payload = {"items": [
            {"keyword_id": k, "kw_type": "LOCALIDADE"}
            for k in kw_ids
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 3, body
        assert body["not_found"] == [], body
        assert body["invalid"] == [], body
        # Confirma no Supabase: kw_type atualizado
        rows = await lg_conn.fetch(
            "SELECT id, kw_type FROM kw_staging WHERE id = ANY($1::int[])",
            kw_ids,
        )
        assert len(rows) == 3, rows
        for row in rows:
            assert row["kw_type"] == "LOCALIDADE"
    finally:
        await _cleanup(pg_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_error_accumulation(pg_conn, lg_conn):
    """T2 (CRIT-8): 2 válidos + 2 IDs inexistentes + 1 kw_type inválido → 200 com relatório."""
    pid, kw_ids = await _seed(pg_conn, lg_conn, n=2)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "kw_type": "SURPRESA"},
            {"keyword_id": kw_ids[1], "kw_type": "SERVICO"},
            {"keyword_id": 99999991, "kw_type": "LOCALIDADE"},
            {"keyword_id": 99999992, "kw_type": "PAGINA_GEO"},
            {"keyword_id": kw_ids[0], "kw_type": "invalido_tipo"},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 2, body
        assert sorted(body["not_found"]) == [99999991, 99999992], body
        assert len(body["invalid"]) == 1, body
        assert body["invalid"][0]["id"] == kw_ids[0]
        assert "kw_type" in body["invalid"][0]["reason"].lower()
    finally:
        await _cleanup(pg_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_invalid_type(pg_conn, lg_conn):
    """T3: kw_type fora do vocabulário aceito → invalid[], sem UPDATE."""
    pid, kw_ids = await _seed(pg_conn, lg_conn, n=1)
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[0], "kw_type": "TIPO_INVALIDO"},
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 0, body
        assert body["not_found"] == [], body
        assert len(body["invalid"]) == 1, body
        assert body["invalid"][0]["id"] == kw_ids[0]
        assert "kw_type" in body["invalid"][0]["reason"].lower()
        # Confirma no Supabase: kw_type não alterado
        row = await lg_conn.fetchrow("SELECT kw_type FROM kw_staging WHERE id = $1", kw_ids[0])
        assert row["kw_type"] == "PAGINA_PRINCIPAL"
    finally:
        await _cleanup(pg_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_idempotente(pg_conn, lg_conn):
    """T4: rerun idêntico → mesmo updated=3 (UPDATE não-destrutivo, idempotente)."""
    pid, kw_ids = await _seed(pg_conn, lg_conn, n=3)
    try:
        payload = {"items": [
            {"keyword_id": k, "kw_type": "SURPRESA"}
            for k in kw_ids
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
            r2 = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["updated"] == 3, r1.json()
        assert r2.json()["updated"] == 3, r2.json()
    finally:
        await _cleanup(pg_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_size_guard_empty():
    """T5 (size guard): {items: []} → 422 (min_length=1 no Pydantic)."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(f"/pesquisas/{fake}/keywords/bulk-reclassify", json={"items": []})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_reclassify_pesquisa_404():
    """T6: UUID randômico → 404 pt-BR."""
    fake = str(uuid.uuid4())
    payload = {"items": [{"keyword_id": 1, "kw_type": "SURPRESA"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(f"/pesquisas/{fake}/keywords/bulk-reclassify", json=payload)
    assert r.status_code == 404
    assert "Pesquisa" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bulk_reclassify_pesquisa_id_malformado_422():
    """T6b: path param que não é UUID → 422 pt-BR, e não 500.

    Vale como prova de ORDEM: o 422 vem do Postgres, antes de qualquer ida ao Supabase.
    """
    payload = {"items": [{"keyword_id": 1, "kw_type": "SURPRESA"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch("/pesquisas/nao-e-uuid/keywords/bulk-reclassify", json=payload)
    assert r.status_code == 422, r.text
    assert "UUID" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bulk_reclassify_all_allowed_types(pg_conn, lg_conn):
    """T7: todos os kw_types permitidos são aceitos."""
    allowed = ["PAGINA_PRINCIPAL", "PAGINA_GEO", "LOCALIDADE", "SECAO", "SURPRESA", "DESCARTA", "SERVICO"]
    pid, kw_ids = await _seed(pg_conn, lg_conn, n=len(allowed))
    try:
        payload = {"items": [
            {"keyword_id": kw_ids[i], "kw_type": t}
            for i, t in enumerate(allowed)
        ]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == len(allowed), body
        assert body["invalid"] == [], body
        rows = await lg_conn.fetch(
            "SELECT kw_type FROM kw_staging WHERE id = ANY($1::int[]) ORDER BY id",
            kw_ids,
        )
        result_types = {row["kw_type"] for row in rows}
        assert result_types == set(allowed)
    finally:
        await _cleanup(pg_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_isola_por_pesquisa(pg_conn, lg_conn):
    """T8 (T-35-05): id de keyword de OUTRA pesquisa não é atualizado.

    Sem a FK cross-DB, o `AND kw_staging.pesquisa_id = $3::uuid` do UPDATE é o único
    controle no banco contra um `keyword_id` forjado no corpo. Este teste falha se
    alguém removê-lo.
    """
    pid_a, kws_a = await _seed(pg_conn, lg_conn, n=1)
    pid_b, kws_b = await _seed(pg_conn, lg_conn, n=1)
    try:
        payload = {"items": [{"keyword_id": kws_b[0], "kw_type": "DESCARTA"}]}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid_a}/keywords/bulk-reclassify", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 0, body
        assert body["not_found"] == [kws_b[0]], body
        # A keyword da pesquisa B continua intocada.
        row = await lg_conn.fetchrow("SELECT kw_type FROM kw_staging WHERE id = $1", kws_b[0])
        assert row["kw_type"] == "PAGINA_PRINCIPAL"
    finally:
        await _cleanup(pg_conn, lg_conn, pid_a)
        await _cleanup(pg_conn, lg_conn, pid_b)


@pytest.mark.asyncio
async def test_bulk_reclassify_lote_grande(pg_conn, lg_conn):
    """T9 (Pitfall 8): 500 itens num request só, abaixo de 5 s de parede.

    É a regressão do laço item a item: com um `execute` por keyword atravessando a
    internet até o Supabase, 500 itens custariam 500 RTTs e o teste estouraria o prazo.
    Em lote o custo de rede é constante.

    O primeiro request é deliberadamente pequeno e NÃO entra na medição: ele paga o
    handshake TLS e a criação do pool (`min_size=1`), que é custo de processo, não de
    lote. O que está sob medição é o custo por item.
    """
    n = 500
    pid, kw_ids = await _seed(pg_conn, lg_conn, n=n)
    assert len(kw_ids) == n, f"seed incompleto: {len(kw_ids)}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Aquecimento: abre os dois pools sem contaminar a medição.
            aq = await c.patch(
                f"/pesquisas/{pid}/keywords/bulk-reclassify",
                json={"items": [{"keyword_id": kw_ids[0], "kw_type": "SECAO"}]},
            )
            assert aq.status_code == 200, aq.text

            payload = {"items": [
                {"keyword_id": k, "kw_type": "LOCALIDADE"} for k in kw_ids
            ]}
            t0 = time.monotonic()
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-reclassify", json=payload)
            decorrido = time.monotonic() - t0

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == n, body
        assert body["not_found"] == [], body
        assert body["invalid"] == [], body
        assert decorrido < 5.0, f"lote de {n} itens levou {decorrido:.2f}s (limite 5s)"

        # Efeito real no Supabase, não só na resposta.
        atualizadas = await lg_conn.fetchval(
            "SELECT count(*) FROM kw_staging WHERE pesquisa_id = $1::uuid AND kw_type = 'LOCALIDADE'",
            pid,
        )
        assert atualizadas == n, atualizadas
        print(f"\n[lote grande] {n} itens em {decorrido:.2f}s")
    finally:
        await _cleanup(pg_conn, lg_conn, pid)
