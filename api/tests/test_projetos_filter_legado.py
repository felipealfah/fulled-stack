"""KWMGMT-06 — testes do filtro id_int_legado em GET /projetos/.

Padrão test_bulk_intel.py: seed via asyncpg direto, invocação via ASGITransport.

Pré-condições:
- Postgres acessível (local: localhost:5432 ou túnel VPS: localhost:5434).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    DATABASE_URL=postgres://fulled:9n7dx5GRZ4Pd20XEkN5zvj4AVqtWS8G8@localhost:5432/fulled \\
    .venv/bin/python -m pytest api/tests/test_projetos_filter_legado.py -v
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


async def _seed_projeto(conn, suffix: str | None = None) -> dict:
    """Cria projeto com nome único. Retorna dict com id (uuid) e id_int_legado."""
    suffix = suffix or uuid.uuid4().hex[:8]
    row = await conn.fetchrow(
        """INSERT INTO projetos (projeto_nome, nicho, cidade)
           VALUES ($1, $2, 'Brasília') RETURNING id, id_int_legado""",
        f"Test-LegadoFilter-{suffix}",
        f"nicho-legado-{suffix}",
    )
    return {"id": str(row["id"]), "id_int_legado": row["id_int_legado"]}


async def _cleanup_projeto(conn, projeto_id: str):
    await conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_id)


@pytest.mark.asyncio
async def test_filter_by_id_int_legado(db_conn):
    """T1: seed projeto, filtrar pelo id_int_legado gerado, assert resultado correto."""
    projeto = await _seed_projeto(db_conn)
    try:
        id_int = projeto["id_int_legado"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/projetos/", params={"id_int_legado": id_int})
        assert r.status_code == 200, r.text
        body = r.json()
        # Deve retornar exatamente 1 resultado (o projeto criado)
        matching = [p for p in body if p["id_int_legado"] == id_int]
        assert len(matching) == 1, f"Esperado 1 resultado com id_int_legado={id_int}, obtido: {len(matching)}"
        assert str(matching[0]["id"]) == projeto["id"]
    finally:
        await _cleanup_projeto(db_conn, projeto["id"])


@pytest.mark.asyncio
async def test_filter_returns_empty_when_no_match(db_conn):
    """T2: GET ?id_int_legado=999998999 com valor improvável → lista vazia, status 200."""
    # Valor muito alto — improvável de existir; limpar se existir por acidente
    await db_conn.execute(
        "DELETE FROM projetos WHERE id_int_legado = 999998999"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/projetos/", params={"id_int_legado": 999998999})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == [], f"Esperado lista vazia, obtido: {body}"
