"""Plan 32-03 — DELETE /pesquisas/{id} com guard de projeto em produção (KWMGMT-03).

Testes cobrem:
- Delete normal (projeto rascunho) — sem guard
- Guard ativado quando projeto em produção (status=deploy) sem force
- Force=true ignora guard
- UUID inexistente → 404
- Delete limpa kw_staging via cascade

Pré-condições:
- Postgres local em localhost:5432 (docker compose).
- Migration 030 aplicada (kw_mgmt router ativo).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_pesquisa_delete_guard.py -v
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


async def _seed_projeto(conn, status: str = "research") -> str:
    """Cria um projeto e retorna o UUID (str)."""
    suffix = uuid.uuid4().hex[:8]
    proj_id = await conn.fetchval(
        """INSERT INTO projetos (projeto_nome, nicho, cidade, status)
           VALUES ($1, $2, 'Brasília', $3) RETURNING id""",
        f"Test-Delete-Guard-{suffix}",
        f"nicho-delete-{suffix}",
        status,
    )
    return str(proj_id)


async def _seed_pesquisa(conn, projeto_id_uuid: str | None = None, n_kws: int = 0) -> tuple[str, list[int]]:
    """Cria pesquisa + n_kws keywords. Retorna (pesquisa_id_str, [kw_ids])."""
    suffix = uuid.uuid4().hex[:8]
    pid = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'pending_review', $3::uuid) RETURNING id""",
        f"Test-DeletePesq-{suffix}",
        f"nicho-pesq-{suffix}",
        projeto_id_uuid,
    )
    kw_ids = []
    for i in range(n_kws):
        kwid = await conn.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, 'PAGINA_PRINCIPAL', 'pending') RETURNING id""",
            pid,
            f"kw-del-{suffix}-{i}",
        )
        kw_ids.append(kwid)
    return str(pid), kw_ids


async def _cleanup_projeto(conn, projeto_id: str):
    """Remove projeto (pesquisas e kw_staging em cascade)."""
    # Desvincular pesquisa_id_atual para não bloquear FK
    await conn.execute(
        "UPDATE projetos SET pesquisa_id_atual = NULL WHERE id = $1::uuid", projeto_id
    )
    # pesquisas têm FK para projetos (ON DELETE SET NULL) — apagar pesquisas primeiro via cascade kw_staging
    await conn.execute(
        "DELETE FROM pesquisas WHERE projeto_id_uuid = $1::uuid", projeto_id
    )
    await conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_id)


@pytest.mark.asyncio
async def test_delete_projeto_rascunho_hard(db_conn):
    """T1: projeto status='research' + pesquisa + 3 kws → DELETE → 200, deleted_keywords=3."""
    proj_id = await _seed_projeto(db_conn, status="research")
    pid, kw_ids = await _seed_pesquisa(db_conn, projeto_id_uuid=proj_id, n_kws=3)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted_keywords"] == 3
        assert body["soft"] is False
        # Pesquisa não deve mais existir
        row = await db_conn.fetchrow("SELECT id FROM pesquisas WHERE id = $1::uuid", pid)
        assert row is None, "Pesquisa ainda existe após DELETE"
    finally:
        await _cleanup_projeto(db_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_guard_projeto_deploy(db_conn):
    """T2: projeto status='deploy' + pesquisa → DELETE sem force → 409, pesquisa ainda existe."""
    proj_id = await _seed_projeto(db_conn, status="deploy")
    pid, _ = await _seed_pesquisa(db_conn, projeto_id_uuid=proj_id, n_kws=1)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 409, r.text
        assert "produção" in r.json()["detail"] or "deploy" in r.json()["detail"]
        # Pesquisa ainda deve existir
        row = await db_conn.fetchrow("SELECT id FROM pesquisas WHERE id = $1::uuid", pid)
        assert row is not None, "Pesquisa foi deletada mesmo com guard ativo"
    finally:
        # Limpar manualmente (guard bloqueou o delete)
        await db_conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pid)
        await db_conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pid)
        await _cleanup_projeto(db_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_force_hard_over_deploy(db_conn):
    """T3: projeto status='deploy' + pesquisa → DELETE ?force=true → 200, pesquisa sumiu."""
    proj_id = await _seed_projeto(db_conn, status="deploy")
    pid, _ = await _seed_pesquisa(db_conn, projeto_id_uuid=proj_id, n_kws=0)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}?force=true")
        assert r.status_code == 200, r.text
        # Pesquisa não deve mais existir
        row = await db_conn.fetchrow("SELECT id FROM pesquisas WHERE id = $1::uuid", pid)
        assert row is None, "Pesquisa ainda existe após DELETE force=true"
    finally:
        await _cleanup_projeto(db_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_pesquisa_not_found():
    """T4: DELETE UUID inexistente → 404."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(f"/pesquisas/{fake}")
    assert r.status_code == 404, r.text
    assert "Pesquisa" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_limpa_kws(db_conn):
    """T5: seed + 3 kws → DELETE → COUNT kw_staging == 0 para essa pesquisa."""
    proj_id = await _seed_projeto(db_conn, status="research")
    pid, kw_ids = await _seed_pesquisa(db_conn, projeto_id_uuid=proj_id, n_kws=3)
    try:
        # Confirmar que kws existem antes
        count_before = await db_conn.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid", pid
        )
        assert count_before == 3

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 200, r.text

        # kw_staging deve estar limpa (CASCADE do FK pesquisas→kw_staging)
        count_after = await db_conn.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE id = ANY($1::int[])", kw_ids
        )
        assert count_after == 0, f"Ainda existem {count_after} kws após DELETE"
    finally:
        await _cleanup_projeto(db_conn, proj_id)
