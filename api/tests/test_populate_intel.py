"""Plan 32-03 — POST /projetos/{id}/seo-plan/populate-intel (KWMGMT-04).

Testes cobrem:
- Happy path: 1 page com kw_principal_id → pages_updated=1, difficulty mapeado
- Fallback max competitive_score quando kw_principal_id é NULL
- Sem intel disponível → pages_sem_intel contém o page_id
- Idempotência: dois POSTs → pages_updated=1 nas duas chamadas
- Projeto não encontrado → 404

Pré-condições:
- Postgres local em localhost:5432 (docker compose).
- Migration 030 bloco B aplicado (CHECK difficulty tolerante).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_populate_intel.py -v
"""

import os
import sys
import uuid
from pathlib import Path

# Override DATABASE_URL para postgres local (5432) antes de qualquer import da app.
os.environ["DATABASE_URL"] = "postgres://fulled:9n7dx5GRZ4Pd20XEkN5zvj4AVqtWS8G8@localhost:5432/fulled"
os.environ["AUTH_ENABLED"] = "false"

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
    """Fecha o pool antes/depois de cada teste."""
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


# ---------------------------------------------------------------------------
# Helpers de seed
# ---------------------------------------------------------------------------

async def _seed_projeto(conn) -> tuple[str, int]:
    """Cria projeto e retorna (uuid_str, id_int_legado)."""
    suffix = uuid.uuid4().hex[:8]
    row = await conn.fetchrow(
        """INSERT INTO projetos (projeto_nome, nicho, cidade, status)
           VALUES ($1, $2, 'Brasília', 'research') RETURNING id, id_int_legado""",
        f"Test-PopIntel-{suffix}",
        f"nicho-popintel-{suffix}",
    )
    return str(row["id"]), row["id_int_legado"]


async def _seed_pesquisa(conn, projeto_id_uuid: str) -> str:
    """Cria pesquisa vinculada ao projeto. Retorna pesquisa_id (uuid str)."""
    suffix = uuid.uuid4().hex[:8]
    pid = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'gate_2_approved', $3::uuid) RETURNING id""",
        f"Test-PopIntel-Pesq-{suffix}",
        f"nicho-pesq-pi-{suffix}",
        projeto_id_uuid,
    )
    return str(pid)


async def _seed_kw(conn, pesquisa_id: str, competitive_score: float | None = None,
                   difficulty_label: str | None = None) -> int:
    """Cria kw_staging. Retorna kw_id (int)."""
    suffix = uuid.uuid4().hex[:6]
    kwid = await conn.fetchval(
        """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status,
                                   competitive_score, difficulty_label, top_competitor_url)
           VALUES ($1::uuid, $2, 'PAGINA_PRINCIPAL', 'approved', $3, $4, $5) RETURNING id""",
        pesquisa_id,
        f"kw-pi-{suffix}",
        competitive_score,
        difficulty_label,
        "https://exemplo.com" if competitive_score is not None else None,
    )
    return kwid


async def _seed_seo_plan(conn, pid_int: int) -> int:
    """Cria projeto_seo_plan. Retorna plan_id (int)."""
    plan_id = await conn.fetchval(
        """INSERT INTO projeto_seo_plan (projeto_id, status)
           VALUES ($1, 'rascunho') RETURNING id""",
        pid_int,
    )
    return plan_id


async def _seed_page(conn, plan_id: int, pesquisa_id: str,
                     kw_principal_id: int | None = None) -> int:
    """Cria projeto_seo_plan_pages. Retorna page_id (int)."""
    page_id = await conn.fetchval(
        """INSERT INTO projeto_seo_plan_pages (plan_id, pesquisa_id, kw_principal_id, papel)
           VALUES ($1, $2::uuid, $3, 'principal') RETURNING id""",
        plan_id,
        pesquisa_id,
        kw_principal_id,
    )
    return page_id


async def _cleanup(conn, projeto_uuid: str, pid_int: int):
    """Cleanup em ordem reversa das FKs."""
    # projeto_seo_plan_pages → em cascade quando plan deletado
    await conn.execute("DELETE FROM projeto_seo_plan WHERE projeto_id = $1", pid_int)
    await conn.execute("DELETE FROM kw_staging WHERE pesquisa_id IN (SELECT id FROM pesquisas WHERE projeto_id_uuid = $1::uuid)", projeto_uuid)
    await conn.execute("DELETE FROM pesquisas WHERE projeto_id_uuid = $1::uuid", projeto_uuid)
    await conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_uuid)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_populate_intel_happy(db_conn):
    """T1: 1 page, kw com score=42, label='LOW' → pages_updated=1, difficulty='baixo'."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_id = await _seed_kw(db_conn, pesq_id, competitive_score=42.0, difficulty_label="LOW")
        plan_id = await _seed_seo_plan(db_conn, pid_int)
        page_id = await _seed_page(db_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 1
        assert body["pages_sem_intel"] == []

        row = await db_conn.fetchrow(
            "SELECT competitive_score, difficulty_label FROM projeto_seo_plan_pages WHERE id = $1",
            page_id,
        )
        assert row["competitive_score"] == 42
        assert row["difficulty_label"] == "baixo"
    finally:
        await _cleanup(db_conn, proj_uuid, pid_int)


@pytest.mark.asyncio
async def test_populate_intel_fallback_max_score(db_conn):
    """T2: page sem kw_principal_id, 3 kws com scores 30/50/20 → recebe kw score=50."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_ids = []
        for score in [30.0, 50.0, 20.0]:
            kw_id = await _seed_kw(db_conn, pesq_id, competitive_score=score, difficulty_label="MED")
            kw_ids.append(kw_id)

        plan_id = await _seed_seo_plan(db_conn, pid_int)
        page_id = await _seed_page(db_conn, plan_id, pesq_id, kw_principal_id=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 1
        assert body["pages_sem_intel"] == []

        row = await db_conn.fetchrow(
            "SELECT competitive_score FROM projeto_seo_plan_pages WHERE id = $1",
            page_id,
        )
        assert row["competitive_score"] == 50, f"Esperava score 50 (max), recebi {row['competitive_score']}"
    finally:
        await _cleanup(db_conn, proj_uuid, pid_int)


@pytest.mark.asyncio
async def test_populate_intel_pages_sem_intel(db_conn):
    """T3: page com kw que tem competitive_score=NULL → pages_updated=0, pages_sem_intel=[page_id]."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_id = await _seed_kw(db_conn, pesq_id, competitive_score=None, difficulty_label=None)
        plan_id = await _seed_seo_plan(db_conn, pid_int)
        page_id = await _seed_page(db_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 0
        assert page_id in body["pages_sem_intel"]
    finally:
        await _cleanup(db_conn, proj_uuid, pid_int)


@pytest.mark.asyncio
async def test_populate_intel_idempotent(db_conn):
    """T4: POST 2× → pages_updated=1 nas duas chamadas."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_id = await _seed_kw(db_conn, pesq_id, competitive_score=60.0, difficulty_label="HIGH")
        plan_id = await _seed_seo_plan(db_conn, pid_int)
        await _seed_page(db_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
            r2 = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")

        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r1.json()["pages_updated"] == 1
        assert r2.json()["pages_updated"] == 1
    finally:
        await _cleanup(db_conn, proj_uuid, pid_int)


@pytest.mark.asyncio
async def test_populate_intel_projeto_not_found():
    """T5: POST em UUID inexistente → 404."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{fake}/seo-plan/populate-intel")
    assert r.status_code == 404, r.text
    assert "Projeto" in r.json()["detail"]
