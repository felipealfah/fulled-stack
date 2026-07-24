"""Testes REQ-8-08: POST /pesquisas/ retorna 409 com pesquisa_id existente após retry.

Pré-condições:
- Túnel VPS Postgres aberto em localhost:5434 (docker compose exec do túnel).
- Migration 027 aplicada (UNIQUE natural pesquisas_natural_key).
- AUTH_ENABLED=false (setado no conftest.py).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_pesquisas_conflict.py -v
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Garante que api/ está no path para importar main.py como top-level
_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from main import app  # noqa: E402
import db as db_module  # noqa: E402


# UUID real do projeto MM Entulho no VPS (id_int_legado=8).
# Verificado via psql em 2026-07-24.
PROJETO_UUID_MM_ENTULHO = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Fecha o pool asyncpg antes de cada teste.

    Pool é módulo-global (db._pool). Sem reset, o pool criado no evento loop
    do teste anterior fica preso e o próximo teste falha com
    'Event loop is closed'. Cada teste cria seu próprio pool na chamada
    inicial de get_pool() (via lifespan da app OU dentro do handler).
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
def unique_pesquisa_payload_sem_projeto():
    """Payload novo (nicho único) com projeto_id=None — órfã para testes de NULL."""
    suffix = uuid.uuid4().hex[:8]
    return {
        "projeto_nome": f"Pytest Fixture {suffix}",
        "nicho": f"nicho-test-{suffix}",
        "cidade": "Brasília",
        "papel": "principal",
        "projeto_id": None,
        "keywords": [
            {"keyword": "teste kw 1", "kw_type": "PAGINA_PRINCIPAL", "avg_monthly_searches": 100},
            {"keyword": "teste kw 2", "kw_type": "DESCARTA"},
        ],
    }


@pytest.fixture
def unique_pesquisa_payload_com_projeto():
    """Payload novo com projeto_id_uuid não-NULL (MM Entulho existente)."""
    suffix = uuid.uuid4().hex[:8]
    return {
        "projeto_nome": "MM Entulho",
        "nicho": f"nicho-conflict-{suffix}",
        "cidade": "Brasília",
        "papel": "servico",
        "projeto_id": PROJETO_UUID_MM_ENTULHO,
        "keywords": [
            {"keyword": "kw teste conflict", "kw_type": "PAGINA_PRINCIPAL"},
        ],
    }


async def _cleanup_pesquisa_por_nicho(nicho: str):
    """Remove pesquisa criada pelos testes para manter idempotência entre runs."""
    import asyncpg
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    try:
        # kw_staging cascateia via ON DELETE CASCADE
        await conn.execute(
            "DELETE FROM agent_executions WHERE pesquisa_id IN (SELECT id FROM pesquisas WHERE nicho = $1)",
            nicho,
        )
        await conn.execute("DELETE FROM pesquisas WHERE nicho = $1", nicho)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_post_pesquisa_happy_path(unique_pesquisa_payload_sem_projeto):
    """T1: primeiro POST cria pesquisa e retorna 200."""
    payload = unique_pesquisa_payload_sem_projeto
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/pesquisas/", json=payload)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "pesquisa" in body
            assert body["pesquisa"]["nicho"] == payload["nicho"]
            assert body["keywords_inseridas"] == 1  # 1 kw (a DESCARTA é ignorada)
            assert body["keywords_ignoradas_descarta"] == 1
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_post_pesquisa_com_projeto_id_null_permite_duplicata(
    unique_pesquisa_payload_sem_projeto,
):
    """T3: com projeto_id_uuid=NULL a UNIQUE default (NULLs distintos) NÃO dispara.

    Documenta a semântica aceita pelo Board (D-08): a órfã foi deletada; se
    outra órfã aparecer futuramente, duplicatas ficam permitidas — filtro real
    é responsabilidade do consumidor (skill não deve criar pesquisa órfã).
    """
    payload = unique_pesquisa_payload_sem_projeto
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post("/pesquisas/", json=payload)
            assert r1.status_code == 200, r1.text
            r2 = await c.post("/pesquisas/", json=payload)
            # Comportamento aceito: NULLs distintos → 200 duas vezes
            assert r2.status_code == 200, r2.text
            assert r2.json()["pesquisa"]["id"] != r1.json()["pesquisa"]["id"]
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_post_pesquisa_conflict_with_projeto_id(
    unique_pesquisa_payload_com_projeto,
):
    """T2 (CRIT-5): retry com projeto_id_uuid não-NULL → 409 com id existente."""
    payload = unique_pesquisa_payload_com_projeto
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post("/pesquisas/", json=payload)
            assert r1.status_code == 200, r1.text
            first_id = r1.json()["pesquisa"]["id"]

            r2 = await c.post("/pesquisas/", json=payload)
            assert r2.status_code == 409, r2.text
            detail = r2.json()["detail"]
            assert detail["error"] == "Pesquisa já existe"
            assert detail["pesquisa_id"] == first_id
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_post_pesquisa_missing_projeto_nome_returns_422():
    """T4: payload sem projeto_nome (campo obrigatório do Pydantic) → 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/pesquisas/", json={"nicho": "x", "cidade": "y"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_pesquisa_rollback_no_orphan_kw(
    unique_pesquisa_payload_com_projeto,
):
    """T5: após retry 409, kw_staging não fica com rows duplicadas.

    O rollback da transaction quando raise HTTPException dentro do
    `async with conn.transaction():` reverte a segunda tentativa. A única
    keyword 'kw teste conflict' deve existir 1x (da primeira inserção).
    """
    payload = unique_pesquisa_payload_com_projeto
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post("/pesquisas/", json=payload)
            assert r1.status_code == 200
            r2 = await c.post("/pesquisas/", json=payload)
            assert r2.status_code == 409

        # Verifica que só existe 1 kw_staging para essa pesquisa (não 2).
        import asyncpg
        dsn = os.environ["DATABASE_URL"]
        conn = await asyncpg.connect(dsn)
        try:
            count = await conn.fetchval(
                """SELECT COUNT(*) FROM kw_staging k
                     JOIN pesquisas p ON p.id = k.pesquisa_id
                    WHERE p.nicho = $1 AND p.projeto_id_uuid = $2::uuid""",
                payload["nicho"], PROJETO_UUID_MM_ENTULHO,
            )
            assert count == 1, f"kw_staging duplicado: {count} rows (esperado 1)"
        finally:
            await conn.close()
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])
