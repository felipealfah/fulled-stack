"""REQ-8-04 — PATCH /pesquisas/{uuid}/keywords/bulk-intel.

Bulk UPDATE com error accumulation. Nunca retorna 500 global — sempre 200
com `{updated, not_found, invalid}`. Vocabulário difficulty_label canônico
(D-04): 'LOW', 'MED', 'HIGH' — outros valores vão para invalid[].

Estratégia: seed pesquisa + kw_staging pending no VPS, chama endpoint,
valida efeito via SELECT, cleanup no teardown.

Pré-condições:
- Túnel VPS Postgres em localhost:5434.
- Migration 017 aplicada (colunas competitive_score/difficulty_label/intel_json em kw_staging).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_bulk_intel.py -v
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
        f"Test-Bulk-Intel-{suffix}", f"nicho-bulk-{suffix}",
    )
    kw_ids = []
    for i in range(n):
        kwid = await conn.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, 'PAGINA_PRINCIPAL', 'pending') RETURNING id""",
            pid, f"kw-bulk-{suffix}-{i}",
        )
        kw_ids.append(kwid)
    return str(pid), kw_ids


async def _cleanup(conn, pesquisa_id):
    await conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id)
    await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


@pytest.mark.asyncio
async def test_bulk_intel_happy(db_conn):
    """T1: 3 items válidos → updated=3, not_found=[], invalid=[]."""
    pid, kw_ids = await _seed(db_conn, n=3)
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_error_accumulation(db_conn):
    """T2 (CRIT-8): 2 válidos + 2 IDs inexistentes + 1 label inválido → 200 com relatório."""
    pid, kw_ids = await _seed(db_conn, n=2)
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_difficulty_label_lowercase_invalid(db_conn):
    """T3 (D-04): 'baixo'/'médio'/'alto' → invalid[], sem UPDATE."""
    pid, kw_ids = await _seed(db_conn, n=1)
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_score_out_of_range(db_conn):
    """T4: competitive_score=150 → invalid[]."""
    pid, kw_ids = await _seed(db_conn, n=1)
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_empty_payload(db_conn):
    """T5: {items: []} → {updated: 0, not_found: [], invalid: []} (200)."""
    pid, _ = await _seed(db_conn, n=0)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/pesquisas/{pid}/keywords/bulk-intel", json={"items": []})
        assert r.status_code == 200
        assert r.json() == {"updated": 0, "not_found": [], "invalid": []}
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_pesquisa_404():
    """T6: UUID randômico → 404 pt-BR."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(f"/pesquisas/{fake}/keywords/bulk-intel", json={"items": []})
    assert r.status_code == 404
    assert "Pesquisa" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bulk_intel_idempotent(db_conn):
    """T7: rerun idêntico → mesmo updated=3 (UPDATE não-destrutivo)."""
    pid, kw_ids = await _seed(db_conn, n=3)
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_bulk_intel_all_canonical_labels(db_conn):
    """T8: LOW, MED, HIGH todos aceitos."""
    pid, kw_ids = await _seed(db_conn, n=3)
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
        await _cleanup(db_conn, pid)
