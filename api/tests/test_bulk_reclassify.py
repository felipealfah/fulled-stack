"""KWMGMT-01 — PATCH /pesquisas/{uuid}/keywords/bulk-reclassify.

Bulk UPDATE de kw_type em kw_staging com error accumulation.
Nunca retorna 500 global — sempre 200 com `{updated, not_found, invalid}`.
Tipos aceitos: PAGINA_PRINCIPAL, PAGINA_GEO, LOCALIDADE, SECAO, SURPRESA, DESCARTA, SERVICO.

Estratégia: seed pesquisa + kw_staging pending no banco local, chama endpoint,
valida efeito via SELECT, cleanup no teardown.

Pré-condições:
- Postgres local em localhost:5432 (docker-compose-local.yml) OU túnel VPS em localhost:5434.
- Migration 030 aplicada (kw_type CHECK inclui LOCALIDADE e SURPRESA; pesquisas.deleted_at existe).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    DATABASE_URL=postgres://fulled:9n7dx5GRZ4Pd20XEkN5zvj4AVqtWS8G8@localhost:5432/fulled \\
        .venv/bin/python -m pytest api/tests/test_bulk_reclassify.py -v
"""

import os
import sys
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
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    yield conn
    await conn.close()


async def _seed(conn, n=3):
    """Cria pesquisa + n kw_staging pending. Retorna (pesquisa_id_str, [kw_id_int, ...])."""
    suffix = uuid.uuid4().hex[:8]
    pid = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel)
           VALUES ($1, $2, 'Brasília', 'classificado', 'principal') RETURNING id""",
        f"Test-Bulk-Reclassify-{suffix}", f"nicho-reclassify-{suffix}",
    )
    kw_ids = []
    for i in range(n):
        kwid = await conn.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, 'PAGINA_PRINCIPAL', 'pending') RETURNING id""",
            pid, f"kw-reclassify-{suffix}-{i}",
        )
        kw_ids.append(kwid)
    return str(pid), kw_ids


async def _cleanup(conn, pesquisa_id):
    await conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id)
    await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


@pytest.mark.asyncio
async def test_bulk_reclassify_happy(db_conn):
    """T1: 3 items válidos → updated=3, not_found=[], invalid=[]."""
    pid, kw_ids = await _seed(db_conn, n=3)
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
        # Confirma no banco: kw_type atualizado
        rows = await db_conn.fetch(
            "SELECT id, kw_type FROM kw_staging WHERE id = ANY($1::int[])",
            kw_ids,
        )
        for row in rows:
            assert row["kw_type"] == "LOCALIDADE"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_error_accumulation(db_conn):
    """T2 (CRIT-8): 2 válidos + 2 IDs inexistentes + 1 kw_type inválido → 200 com relatório."""
    pid, kw_ids = await _seed(db_conn, n=2)
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_invalid_type(db_conn):
    """T3: kw_type fora do vocabulário aceito → invalid[], sem UPDATE."""
    pid, kw_ids = await _seed(db_conn, n=1)
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
        # Confirma no banco: kw_type não alterado
        row = await db_conn.fetchrow("SELECT kw_type FROM kw_staging WHERE id = $1", kw_ids[0])
        assert row["kw_type"] == "PAGINA_PRINCIPAL"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_reclassify_idempotente(db_conn):
    """T4: rerun idêntico → mesmo updated=3 (UPDATE não-destrutivo, idempotente)."""
    pid, kw_ids = await _seed(db_conn, n=3)
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
        await _cleanup(db_conn, pid)


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
async def test_bulk_reclassify_all_allowed_types(db_conn):
    """T7: todos os kw_types permitidos são aceitos."""
    allowed = ["PAGINA_PRINCIPAL", "PAGINA_GEO", "LOCALIDADE", "SECAO", "SURPRESA", "DESCARTA", "SERVICO"]
    pid, kw_ids = await _seed(db_conn, n=len(allowed))
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
        rows = await db_conn.fetch(
            "SELECT kw_type FROM kw_staging WHERE id = ANY($1::int[]) ORDER BY id",
            kw_ids,
        )
        result_types = {row["kw_type"] for row in rows}
        assert result_types == set(allowed)
    finally:
        await _cleanup(db_conn, pid)
