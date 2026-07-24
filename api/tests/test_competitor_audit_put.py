"""REQ-8-05 — PUT /projetos/{uuid}/competitor-audit.

Upsert em competitor_audits via ON CONFLICT (projeto_id_uuid) DO UPDATE.
UNIQUE INDEX competitor_audits_projeto_uuid_key criado na migration 027 (plan 10-01).

Estratégia: usar Limpa Fossa Brasília (f8b09865...) como fixture, DELETE preventivo
antes de cada teste para começar do zero, cleanup no teardown.

Pré-condições:
- Túnel VPS Postgres em localhost:5434.
- Migration 027 aplicada (UNIQUE projeto_id_uuid em competitor_audits).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_competitor_audit_put.py -v
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


# Limpa Fossa Brasília — id_int_legado=15 (verificado em 2026-07-24 via psql VPS)
PROJETO_LIMPA_UUID = "f8b09865-04f9-4c54-b825-a04606ac8f01"
PROJETO_LIMPA_INT = 15


PAYLOAD_BASE = {
    "slug": "test-competitor-audit-slug",
    "keyword_principal": "kw teste competitor",
    "generated_at": "2026-07-24T10:00:00",
    "competitors": [
        {"url": "https://a.com/x", "position": 1, "domain": "a.com", "estimated_word_count": 1000},
        {"url": "https://b.com/y", "position": 2, "domain": "b.com", "estimated_word_count": 800},
    ],
    "market_gaps": {
        "benchmark_word_count": 900,
        "required_sections": ["hero", "faq"],
        "schema_missing": ["LocalBusiness"],
        "geo_pages_benchmark": 5,
        "backlink_benchmark": 100,
        "trust_gaps": [],
        "summary": "Resumo teste competitor",
    },
    "yaml_path": "/tmp/test-competitor.yaml",
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


async def _cleanup_audit(conn, projeto_uuid):
    await conn.execute(
        "DELETE FROM competitor_audits WHERE projeto_id_uuid = $1::uuid", projeto_uuid,
    )


@pytest.mark.asyncio
async def test_put_creates_audit(db_conn):
    """T1: PUT em projeto sem audit → 200 com registro completo."""
    await _cleanup_audit(db_conn, PROJETO_LIMPA_UUID)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit",
                json=PAYLOAD_BASE,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["competitor_count"] == 2
        assert body["market_gaps"]["benchmark_word_count"] == 900
        assert body["market_gaps"]["summary"] == "Resumo teste competitor"
        assert len(body["competitors"]) == 2
        assert body["slug"] == "test-competitor-audit-slug"
    finally:
        await _cleanup_audit(db_conn, PROJETO_LIMPA_UUID)


@pytest.mark.asyncio
async def test_put_idempotent_only_one_row(db_conn):
    """T2 (CRIT-4): 2 PUTs seguidos → COUNT=1 (ON CONFLICT DO UPDATE)."""
    await _cleanup_audit(db_conn, PROJETO_LIMPA_UUID)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit", json=PAYLOAD_BASE,
            )
            r2 = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit", json=PAYLOAD_BASE,
            )
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        count = await db_conn.fetchval(
            "SELECT COUNT(*) FROM competitor_audits WHERE projeto_id_uuid = $1::uuid",
            PROJETO_LIMPA_UUID,
        )
        assert count == 1, f"esperado 1 row após 2 PUTs (ON CONFLICT), tem {count}"
    finally:
        await _cleanup_audit(db_conn, PROJETO_LIMPA_UUID)


@pytest.mark.asyncio
async def test_put_update_muda_competitor_count(db_conn):
    """T3: PUT com 2 competitors, depois PUT com 4 → competitor_count=4."""
    await _cleanup_audit(db_conn, PROJETO_LIMPA_UUID)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.put(f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit", json=PAYLOAD_BASE)

            bigger = {**PAYLOAD_BASE}
            bigger["competitors"] = [
                {"url": f"https://c{i}.com", "position": i + 1, "domain": f"c{i}.com"}
                for i in range(4)
            ]
            r2 = await c.put(
                f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit", json=bigger,
            )
        assert r2.status_code == 200, r2.text
        assert r2.json()["competitor_count"] == 4
    finally:
        await _cleanup_audit(db_conn, PROJETO_LIMPA_UUID)


@pytest.mark.asyncio
async def test_put_projeto_404():
    """T4: UUID inexistente → 404."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{fake}/competitor-audit", json=PAYLOAD_BASE)
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_put_missing_market_gaps():
    """T5: payload sem market_gaps → 422 Pydantic."""
    bad = {k: v for k, v in PAYLOAD_BASE.items() if k != "market_gaps"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit", json=bad)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_generated_at_invalido():
    """T6: generated_at malformado → 422."""
    bad = {**PAYLOAD_BASE, "generated_at": "ontem"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{PROJETO_LIMPA_UUID}/competitor-audit", json=bad)
    assert r.status_code == 422, r.text
