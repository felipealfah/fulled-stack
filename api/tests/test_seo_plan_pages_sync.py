"""Phase 32-04 — PUT /projetos/{id}/seo-plan/pages/sync

Testa o endpoint de sync estrutural de páginas do vault em content_pages (KWMGMT-02).
Upsert via ON CONFLICT (projeto_id, url) WHERE url IS NOT NULL, error accumulation,
replace/archive opt-in, preservação de campos de revisão.

Pré-condições:
- Migration 030 bloco C aplicada (colunas url, titulo, arquivada, etc. em content_pages).
- Túnel VPS Postgres em localhost:5434 (ou DATABASE_URL configurada no conftest.py).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_seo_plan_pages_sync.py -v
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


# ---------------------------------------------------------------------------
# Fixtures de infraestrutura
# ---------------------------------------------------------------------------

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


@pytest.fixture
async def seed_projeto(db_conn):
    """Cria um projeto com id_int_legado alto. Retorna (projeto_uuid_str, pid_int).
    Cleanup automático: remove content_pages e o projeto."""
    suffix = uuid.uuid4().hex[:8]
    pid_int = 999900 + (int(suffix[:4], 16) % 50)  # evita colisão com projetos reais
    projeto_uuid = str(uuid.uuid4())

    # Garante que não há colisão no id_int_legado
    await db_conn.execute(
        "DELETE FROM content_pages WHERE projeto_id = $1", pid_int
    )
    await db_conn.execute(
        "DELETE FROM projetos WHERE id_int_legado = $1", pid_int
    )

    # INSERT usando as colunas obrigatórias de projetos (sem ON CONFLICT — id_int_legado sem UNIQUE)
    await db_conn.execute(
        """INSERT INTO projetos (id_int_legado, projeto_nome, nicho, cidade, status, tipo, metadata)
           VALUES ($1, $2, $3, 'Brasília', 'research', 'rank_rent', '{}')""",
        pid_int,
        f"TestSync-{suffix}",
        f"nicho-sync-{suffix}",
    )
    # Re-fetch do UUID gerado pelo banco
    row = await db_conn.fetchrow(
        "SELECT id FROM projetos WHERE id_int_legado = $1 ORDER BY created_at DESC LIMIT 1", pid_int
    )
    projeto_uuid_str = str(row["id"])

    yield projeto_uuid_str, pid_int

    # Cleanup
    await db_conn.execute("DELETE FROM content_pages WHERE projeto_id = $1", pid_int)
    await db_conn.execute("DELETE FROM projetos WHERE id_int_legado = $1", pid_int)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(url: str, tipo: str = "servico", titulo: str | None = None, **kwargs) -> dict:
    """Constrói um PageStructuralItem dict."""
    page = {"url": url, "tipo": tipo}
    if titulo is not None:
        page["titulo"] = titulo
    page.update(kwargs)
    return page


async def _seed_page(conn, pid_int: int, url: str, page_slug: str, page_type: str = "service",
                     status: str = "gerado", review_report: dict | None = None,
                     titulo_antigo: str | None = None):
    """Insere uma página diretamente no banco para setup dos testes."""
    import json as _json
    await conn.execute(
        """INSERT INTO content_pages (projeto_id, page_slug, page_type, url, status, review_report)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb)
           ON CONFLICT (projeto_id, page_slug) DO NOTHING""",
        pid_int, page_slug, page_type, url, status,
        _json.dumps(review_report) if review_report else None,
    )


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_happy_created(seed_projeto, db_conn):
    """T1: 3 páginas novas → created=3, updated=0, archived=0, invalid=[]."""
    projeto_uuid, pid_int = seed_projeto
    payload = {
        "pages": [
            _make_page("/", "home"),
            _make_page("/desentupidora-brasilia", "servico", titulo="Desentupidora Brasília"),
            _make_page("/desentupidora-asa-sul", "servico_geo"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 3
    assert body["updated"] == 0
    assert body["archived"] == 0
    assert body["invalid"] == []


@pytest.mark.asyncio
async def test_sync_updated_existing(seed_projeto, db_conn):
    """T2: pre-seed 2 páginas, PUT com mesmas urls e títulos diferentes → updated=2."""
    projeto_uuid, pid_int = seed_projeto
    await _seed_page(db_conn, pid_int, "/servico-a", "servico-a", titulo_antigo="Titulo Antigo A")
    await _seed_page(db_conn, pid_int, "/servico-b", "servico-b")

    payload = {
        "pages": [
            _make_page("/servico-a", "servico", titulo="Titulo Novo A"),
            _make_page("/servico-b", "servico", titulo="Titulo Novo B"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0
    assert body["updated"] == 2
    assert body["archived"] == 0
    assert body["invalid"] == []

    # Confirmar títulos atualizados no banco
    rows = await db_conn.fetch(
        "SELECT url, titulo FROM content_pages WHERE projeto_id = $1 AND url IN ($2, $3)",
        pid_int, "/servico-a", "/servico-b",
    )
    titulos = {r["url"]: r["titulo"] for r in rows}
    assert titulos["/servico-a"] == "Titulo Novo A"
    assert titulos["/servico-b"] == "Titulo Novo B"


@pytest.mark.asyncio
async def test_sync_replace_archives_missing(seed_projeto, db_conn):
    """T3: pre-seed 3 páginas, PUT com 2 + replace=true → archived=1."""
    projeto_uuid, pid_int = seed_projeto
    await _seed_page(db_conn, pid_int, "/pag-a", "pag-a")
    await _seed_page(db_conn, pid_int, "/pag-b", "pag-b")
    await _seed_page(db_conn, pid_int, "/pag-c", "pag-c")

    payload = {
        "replace": True,
        "pages": [
            _make_page("/pag-a", "servico"),
            _make_page("/pag-b", "servico"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["archived"] == 1

    # Confirmar que /pag-c foi arquivada
    row = await db_conn.fetchrow(
        "SELECT arquivada FROM content_pages WHERE projeto_id = $1 AND url = $2",
        pid_int, "/pag-c",
    )
    assert row is not None
    assert row["arquivada"] is True


@pytest.mark.asyncio
async def test_sync_preserva_review_report(seed_projeto, db_conn):
    """T4: ON CONFLICT não sobrescreve review_report, status, approved_at, reviewed_at."""
    projeto_uuid, pid_int = seed_projeto
    review = {"sections": {"hero": {"status": "ok"}}}
    await _seed_page(db_conn, pid_int, "/servico-preservar", "servico-preservar",
                     status="revisado", review_report=review)
    # Marcar approved_at para ter campo preenchido
    await db_conn.execute(
        "UPDATE content_pages SET approved_at = NOW(), reviewed_at = NOW() WHERE projeto_id = $1 AND url = $2",
        pid_int, "/servico-preservar",
    )

    payload = {
        "pages": [
            _make_page("/servico-preservar", "servico", titulo="Titulo Atualizado"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 1

    # Confirmar que status, review_report e datas foram preservados
    row = await db_conn.fetchrow(
        """SELECT status, review_report, approved_at, reviewed_at, titulo
           FROM content_pages WHERE projeto_id = $1 AND url = $2""",
        pid_int, "/servico-preservar",
    )
    assert row["status"] == "revisado"           # não sobrescrito pelo 'gerado' do ON CONFLICT
    assert row["titulo"] == "Titulo Atualizado"  # atualizado pelo sync
    assert row["review_report"] is not None       # preservado
    assert row["approved_at"] is not None         # preservado
    assert row["reviewed_at"] is not None         # preservado


@pytest.mark.asyncio
async def test_sync_mapping_tipo_para_page_type(seed_projeto, db_conn):
    """T5: 4 tipos diferentes → page_types corretos no banco."""
    projeto_uuid, pid_int = seed_projeto
    payload = {
        "pages": [
            _make_page("/", "home"),
            _make_page("/servico", "servico"),
            _make_page("/servico-geo", "servico_geo"),
            _make_page("/localidade", "localidade"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 4

    rows = await db_conn.fetch(
        "SELECT url, page_type FROM content_pages WHERE projeto_id = $1 ORDER BY url",
        pid_int,
    )
    page_types = {row["url"]: row["page_type"] for row in rows}
    assert page_types["/"] == "home"
    assert page_types["/localidade"] == "localidade"
    assert page_types["/servico"] == "service"
    assert page_types["/servico-geo"] == "service_region"


@pytest.mark.asyncio
async def test_sync_error_accumulation(seed_projeto, db_conn):
    """T6: 3 pages (1 válida, 1 tipo inválido, 1 pesquisa_id inválido) → created=1, invalid len=2."""
    projeto_uuid, pid_int = seed_projeto
    payload = {
        "pages": [
            _make_page("/valida", "servico", titulo="Válida"),
            _make_page("/tipo-errado", "tipo_inexistente"),
            _make_page("/pesquisa-id-errado", "servico", pesquisa_id="nao-eh-uuid"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert len(body["invalid"]) == 2
    invalid_urls = {i["url"] for i in body["invalid"]}
    assert "/tipo-errado" in invalid_urls
    assert "/pesquisa-id-errado" in invalid_urls


@pytest.mark.asyncio
async def test_sync_idempotent(seed_projeto, db_conn):
    """T7: PUT 2x com mesmo payload → COUNT inalterado na segunda chamada."""
    projeto_uuid, pid_int = seed_projeto
    payload = {
        "pages": [
            _make_page("/idem-a", "servico", titulo="A"),
            _make_page("/idem-b", "home", titulo="B"),
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)
        r2 = await c.put(f"/projetos/{projeto_uuid}/seo-plan/pages/sync", json=payload)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    b1 = r1.json()
    b2 = r2.json()
    assert b1["created"] == 2
    assert b2["updated"] == 2    # segunda vez são updates, não creates
    assert b2["created"] == 0

    # COUNT não mudou no banco
    count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM content_pages WHERE projeto_id = $1", pid_int
    )
    assert count == 2


@pytest.mark.asyncio
async def test_sync_projeto_not_found():
    """T8: projeto UUID inexistente → 404."""
    fake_uuid = str(uuid.uuid4())
    payload = {"pages": [_make_page("/qualquer", "servico")]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/projetos/{fake_uuid}/seo-plan/pages/sync", json=payload)
    assert r.status_code == 404
    assert "não encontrado" in r.json()["detail"].lower()
