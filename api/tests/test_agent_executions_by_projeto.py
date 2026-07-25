"""Plan 12-02 — POST /projetos/{id}/agent-executions.

Endpoint novo para skills content/site: aceita `pesquisa_id` opcional
(permite site-builder rodar sem pesquisa aprovada) e popula AMBOS
`projeto_id` (INT legado) E `projeto_id_uuid` (FK canônica).

Casos:
  T1: POST com projeto válido + só agent_name/status → 201, row com projeto_id_uuid
      populado + pesquisa_id NULL + projeto_id INT populado
  T2: POST com pesquisa_id opcional → 201, ambas FKs preenchidas
  T3: POST com UUID inexistente → 404
  T4: POST com pesquisa_id inexistente → 404
  T5: POST com status='completed' → completed_at NOT NULL (auto)
  T6: POST com status='pending' → completed_at NULL

Pré-condições:
- Túnel VPS Postgres em localhost:5434.
- Migration 029 aplicada (pesquisa_id nullable).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/pytest api/tests/test_agent_executions_by_projeto.py -v
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


# MM Entulho — id_int_legado=8 (fixture do repo)
PROJETO_MMENTULHO_UUID = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"
PROJETO_MMENTULHO_INT = 8


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


async def _cleanup_probe_executions(conn, projeto_uuid: str, agent_name: str):
    """Remove execuções de teste anteriores (idempotência da suite)."""
    await conn.execute(
        """DELETE FROM agent_executions
           WHERE projeto_id_uuid = $1::uuid AND agent_name = $2""",
        projeto_uuid, agent_name,
    )


@pytest.mark.asyncio
async def test_create_by_projeto_sem_pesquisa(db_conn):
    """T1: POST com só agent_name/status → 201 + projeto_id_uuid + projeto_id INT populados, pesquisa_id NULL."""
    agent = "test_12_02_t1"
    await _cleanup_probe_executions(db_conn, PROJETO_MMENTULHO_UUID, agent)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MMENTULHO_UUID}/agent-executions",
                json={"agent_name": agent, "status": "completed"},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["projeto_id"] == PROJETO_MMENTULHO_UUID
        assert body["status"] == "completed"
        assert isinstance(body["id"], int)

        # Verificar row no DB
        row = await db_conn.fetchrow(
            "SELECT projeto_id, projeto_id_uuid, pesquisa_id, agent_name, status, completed_at "
            "FROM agent_executions WHERE id = $1",
            body["id"],
        )
        assert row["projeto_id"] == PROJETO_MMENTULHO_INT
        assert str(row["projeto_id_uuid"]) == PROJETO_MMENTULHO_UUID
        assert row["pesquisa_id"] is None
        assert row["agent_name"] == agent
        assert row["status"] == "completed"
        assert row["completed_at"] is not None
    finally:
        await _cleanup_probe_executions(db_conn, PROJETO_MMENTULHO_UUID, agent)


@pytest.mark.asyncio
async def test_create_by_projeto_com_pesquisa(db_conn):
    """T2: POST com pesquisa_id opcional → ambas FKs preenchidas."""
    agent = "test_12_02_t2"
    await _cleanup_probe_executions(db_conn, PROJETO_MMENTULHO_UUID, agent)
    # Buscar uma pesquisa real do projeto para usar como fixture
    pesquisa_id = await db_conn.fetchval(
        "SELECT id::text FROM pesquisas WHERE projeto_id_uuid = $1::uuid LIMIT 1",
        PROJETO_MMENTULHO_UUID,
    )
    if not pesquisa_id:
        pytest.skip("MM Entulho não tem pesquisa vinculada — teste T2 requer fixture")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MMENTULHO_UUID}/agent-executions",
                json={
                    "agent_name": agent,
                    "status": "completed",
                    "pesquisa_id": pesquisa_id,
                },
            )
        assert r.status_code == 201, r.text
        body = r.json()

        row = await db_conn.fetchrow(
            "SELECT projeto_id, projeto_id_uuid, pesquisa_id FROM agent_executions WHERE id = $1",
            body["id"],
        )
        assert row["projeto_id"] == PROJETO_MMENTULHO_INT
        assert str(row["projeto_id_uuid"]) == PROJETO_MMENTULHO_UUID
        assert str(row["pesquisa_id"]) == pesquisa_id
    finally:
        await _cleanup_probe_executions(db_conn, PROJETO_MMENTULHO_UUID, agent)


@pytest.mark.asyncio
async def test_create_by_projeto_uuid_inexistente():
    """T3: POST com UUID inexistente → 404 pt-BR."""
    fake_uuid = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/projetos/{fake_uuid}/agent-executions",
            json={"agent_name": "test_t3", "status": "completed"},
        )
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_by_projeto_pesquisa_inexistente():
    """T4: POST com pesquisa_id inexistente → 404 pt-BR."""
    fake_pesq = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/projetos/{PROJETO_MMENTULHO_UUID}/agent-executions",
            json={
                "agent_name": "test_t4",
                "status": "completed",
                "pesquisa_id": fake_pesq,
            },
        )
    assert r.status_code == 404, r.text
    assert "Pesquisa" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_by_projeto_pending_completed_at_null(db_conn):
    """T5: POST com status='pending' → completed_at NULL (só started_at populado)."""
    agent = "test_12_02_t5"
    await _cleanup_probe_executions(db_conn, PROJETO_MMENTULHO_UUID, agent)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MMENTULHO_UUID}/agent-executions",
                json={"agent_name": agent, "status": "pending"},
            )
        assert r.status_code == 201, r.text
        body = r.json()

        row = await db_conn.fetchrow(
            "SELECT status, started_at, completed_at FROM agent_executions WHERE id = $1",
            body["id"],
        )
        assert row["status"] == "pending"
        assert row["started_at"] is not None
        assert row["completed_at"] is None
    finally:
        await _cleanup_probe_executions(db_conn, PROJETO_MMENTULHO_UUID, agent)


@pytest.mark.asyncio
async def test_create_by_projeto_missing_agent_name():
    """T6: POST sem agent_name → 422 Pydantic."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/projetos/{PROJETO_MMENTULHO_UUID}/agent-executions",
            json={"status": "completed"},
        )
    assert r.status_code == 422, r.text
