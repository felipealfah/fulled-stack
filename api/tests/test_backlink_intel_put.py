"""REQ-8-06 — PUT /projetos/{uuid}/backlink-intel.

Upsert em backlink_intel via ON CONFLICT (projeto_id) DO UPDATE.
Tabela criada na migration 028 (plan 10-01) — PK natural: projeto_id UUID.

Estratégia: usar Limpa Fossa Brasília (f8b09865...), DELETE preventivo.

Pré-condições:
- Túnel VPS Postgres em localhost:5434.
- Migration 028 aplicada (tabela backlink_intel).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_backlink_intel_put.py -v
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


PROJETO_LIMPA_UUID = "f8b09865-04f9-4c54-b825-a04606ac8f01"


PAYLOAD_BASE = {
    "slug": "test-backlink-slug",
    "keyword_principal": "kw backlink teste",
    "generated_at": "2026-07-24T10:00:00",
    "summary": {
        "avg_competitor_dofollow_backlinks": 150.0,
        "total_opportunities": 5,
        "high_priority_count": 2,
        "recommended_strategy": "Tier 1 primeiro",
    },
    "competitors_analyzed": [
        {
            "domain": "a.com",
            "dofollow_count": 200,
            "avg_domain_rank": 30.0,
            "avg_spam_score": 0.02,
        },
    ],
    "opportunities": [
        {
            "source": "foursquare.com",
            "tier": 1,
            "priority": "alta",
            "competitor_presente": True,
            "impact": "alto",
            "effort": "baixo",
            "action": "Criar perfil",
        },
    ],
}


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
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


async def _cleanup_backlink(conn, projeto_uuid):
    await conn.execute(
        "DELETE FROM backlink_intel WHERE projeto_id = $1::uuid", projeto_uuid,
    )


@pytest.mark.asyncio
async def test_put_creates_backlink_intel(db_conn):
    """T1: PUT em projeto sem backlink_intel → 200 com registro completo."""
    await _cleanup_backlink(db_conn, PROJETO_LIMPA_UUID)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=PAYLOAD_BASE,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["projeto_id"] == PROJETO_LIMPA_UUID
        assert body["slug"] == "test-backlink-slug"
        assert body["summary"]["total_opportunities"] == 5
        assert body["summary"]["recommended_strategy"] == "Tier 1 primeiro"
        assert len(body["opportunities"]) == 1
        assert body["opportunities"][0]["source"] == "foursquare.com"
    finally:
        await _cleanup_backlink(db_conn, PROJETO_LIMPA_UUID)


@pytest.mark.asyncio
async def test_put_backlink_idempotent_only_one_row(db_conn):
    """T2 (CRIT-4): 2 PUTs → COUNT=1 (PK UUID + ON CONFLICT DO UPDATE)."""
    await _cleanup_backlink(db_conn, PROJETO_LIMPA_UUID)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=PAYLOAD_BASE,
            )
            r2 = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=PAYLOAD_BASE,
            )
        assert r1.status_code == 200
        assert r2.status_code == 200
        count = await db_conn.fetchval(
            "SELECT COUNT(*) FROM backlink_intel WHERE projeto_id = $1::uuid",
            PROJETO_LIMPA_UUID,
        )
        assert count == 1
    finally:
        await _cleanup_backlink(db_conn, PROJETO_LIMPA_UUID)


@pytest.mark.asyncio
async def test_put_backlink_update_muda_opportunities(db_conn):
    """T3: PUT com 1 opportunity, depois PUT com 20 → len(opportunities)=20."""
    await _cleanup_backlink(db_conn, PROJETO_LIMPA_UUID)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.put(f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=PAYLOAD_BASE)

            bigger = {**PAYLOAD_BASE}
            bigger["summary"] = {**PAYLOAD_BASE["summary"], "total_opportunities": 20}
            bigger["opportunities"] = [
                {"source": f"src{i}.com", "tier": (i % 3) + 1, "priority": "media"}
                for i in range(20)
            ]
            r2 = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=bigger,
            )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["summary"]["total_opportunities"] == 20
        assert len(body["opportunities"]) == 20
    finally:
        await _cleanup_backlink(db_conn, PROJETO_LIMPA_UUID)


@pytest.mark.asyncio
async def test_put_backlink_projeto_404():
    """T4: UUID inexistente → 404 (via _resolve_projeto)."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{fake}/backlink-intel", json=PAYLOAD_BASE)
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_put_backlink_missing_summary():
    """T5: payload sem summary → 422."""
    bad = {k: v for k, v in PAYLOAD_BASE.items() if k != "summary"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=bad)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_backlink_generated_at_invalido():
    """T6: generated_at malformado → 422 pt-BR."""
    bad = {**PAYLOAD_BASE, "generated_at": "outrora"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{PROJETO_LIMPA_UUID}/backlink-intel", json=bad)
    assert r.status_code == 422, r.text
