"""Plan 12-02 — content.py aceita projeto_id como UUID no path param.

Antes desta correção, todos os 7 endpoints declaravam `projeto_id: int` e
faziam `SELECT id FROM projetos WHERE id = $1` (comparando UUID com int).
Em prod, retornavam 500 (com int_legado) OU 422 (com UUID) — router INTEIRO
estava órfão da Phase 05.

Fix: path param `projeto_id: str`, resolve via `_resolve_projeto` (retorna
`id_int_legado`) e INSERT/SELECT interno em `content_pages` usa INT como
antes. Também popula `projeto_id_uuid` para o dashboard scoped por projeto.

Casos mínimos (não re-testa todos os 7 endpoints — só o padrão):
  T1: GET com UUID válido → 200 (lista, possivelmente vazia)
  T2: GET com UUID inexistente → 404
  T3: POST upsert com UUID → 200 + row com AMBOS projeto_id INT e projeto_id_uuid
  T4: PATCH section com UUID → 200

Pré-condições:
- Túnel VPS Postgres em localhost:5434.
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/pytest api/tests/test_content_uuid_path.py -v
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


PROJETO_MMENTULHO_UUID = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"
PROJETO_MMENTULHO_INT = 8

TEST_PAGE_SLUG = "test-12-02-uuid-fix"


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


async def _cleanup_test_page(conn):
    await conn.execute(
        "DELETE FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
        PROJETO_MMENTULHO_INT, TEST_PAGE_SLUG,
    )


@pytest.mark.asyncio
async def test_get_content_com_uuid_valido():
    """T1: GET /projetos/{uuid}/content → 200 com lista."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/projetos/{PROJETO_MMENTULHO_UUID}/content")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_get_content_com_uuid_inexistente():
    """T2: GET com UUID inexistente → 404 pt-BR."""
    fake_uuid = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/projetos/{fake_uuid}/content")
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_post_content_popula_ambos_projeto_id(db_conn):
    """T3: POST upsert com UUID → row tem projeto_id INT E projeto_id_uuid populados."""
    await _cleanup_test_page(db_conn)
    try:
        payload = {
            "page_slug": TEST_PAGE_SLUG,
            "page_type": "home",
            "status": "gerado",
            "review_report": {
                "status": "gerado",
                "sections": {"hero": {"status": "ok", "issues": []}},
            },
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MMENTULHO_UUID}/content", json=payload,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page_slug"] == TEST_PAGE_SLUG
        assert body["status"] == "gerado"

        # Verificar row no DB — AMBOS projeto_id (INT) e projeto_id_uuid (UUID)
        row = await db_conn.fetchrow(
            "SELECT projeto_id, projeto_id_uuid, page_slug, status "
            "FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            PROJETO_MMENTULHO_INT, TEST_PAGE_SLUG,
        )
        assert row is not None, "Row não foi criada"
        assert row["projeto_id"] == PROJETO_MMENTULHO_INT
        assert str(row["projeto_id_uuid"]) == PROJETO_MMENTULHO_UUID
        assert row["status"] == "gerado"
    finally:
        await _cleanup_test_page(db_conn)


@pytest.mark.asyncio
async def test_patch_section_com_uuid(db_conn):
    """T4: PATCH section com UUID → 200 + section atualizada."""
    await _cleanup_test_page(db_conn)
    try:
        # Setup: cria page primeiro
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(
                f"/projetos/{PROJETO_MMENTULHO_UUID}/content",
                json={
                    "page_slug": TEST_PAGE_SLUG,
                    "page_type": "home",
                    "status": "gerado",
                    "review_report": {"sections": {}},
                },
            )
            r = await c.patch(
                f"/projetos/{PROJETO_MMENTULHO_UUID}/content/{TEST_PAGE_SLUG}/section",
                json={
                    "section": "hero",
                    "status": "flag",
                    "issues": ["Título fraco"],
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        # review_report pode vir como str (codec JSONB não ativo) ou dict
        import json as _json

        def _to_dict(v):
            return _json.loads(v) if isinstance(v, str) else v

        review = _to_dict(body["review_report"])
        sections = _to_dict(review["sections"])
        hero = _to_dict(sections["hero"])
        assert hero["status"] == "flag"
        assert "Título fraco" in hero["issues"]
    finally:
        await _cleanup_test_page(db_conn)


@pytest.mark.asyncio
async def test_post_content_projeto_inexistente():
    """T5: POST com UUID inexistente → 404."""
    fake_uuid = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/projetos/{fake_uuid}/content",
            json={
                "page_slug": "irrelevante",
                "page_type": "home",
                "status": "gerado",
            },
        )
    assert r.status_code == 404, r.text
