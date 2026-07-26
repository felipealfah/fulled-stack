"""KWMGMT-05 — testes do endpoint GET /projetos/{id}/keywords.

Padrão test_bulk_intel.py: seed via asyncpg direto, invocação via ASGITransport.

Pré-condições:
- Postgres acessível (local: localhost:5432 ou túnel VPS: localhost:5434).
- Migration 030 aplicada.
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    DATABASE_URL=postgres://fulled:9n7dx5GRZ4Pd20XEkN5zvj4AVqtWS8G8@localhost:5432/fulled \\
    .venv/bin/python -m pytest api/tests/test_projeto_keywords_list.py -v
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


async def _seed_projeto_com_kws(conn, n_kws=3, volumes=None, statuses=None, kw_types=None):
    """Cria projeto + pesquisa + N kw_staging.

    Retorna (projeto_id_str, pesquisa_id_str, [kw_id_int, ...]).
    """
    suffix = uuid.uuid4().hex[:8]

    # Criar projeto (NOT NULL obrigatórios: projeto_nome, nicho, cidade — todos têm defaults exceto nome e nicho)
    projeto_id = await conn.fetchval(
        """INSERT INTO projetos (projeto_nome, nicho, cidade)
           VALUES ($1, $2, 'Brasília') RETURNING id""",
        f"Test-KwList-{suffix}",
        f"nicho-kwlist-{suffix}",
    )

    # Criar pesquisa vinculada ao projeto via projeto_id_uuid
    pesquisa_id = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'classificado', 'principal', $3::uuid) RETURNING id""",
        f"Test-KwList-Pesq-{suffix}",
        f"nicho-kwlist-{suffix}",
        str(projeto_id),
    )

    kw_ids = []
    for i in range(n_kws):
        vol = (volumes[i] if volumes and i < len(volumes) else (300 - i * 100))
        st = (statuses[i] if statuses and i < len(statuses) else "pending")
        kt = (kw_types[i] if kw_types and i < len(kw_types) else "PAGINA_PRINCIPAL")
        kwid = await conn.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status, avg_monthly_searches)
               VALUES ($1::uuid, $2, $3, $4, $5) RETURNING id""",
            str(pesquisa_id),
            f"kw-kwlist-{suffix}-{i}",
            kt,
            st,
            vol,
        )
        kw_ids.append(kwid)

    return str(projeto_id), str(pesquisa_id), kw_ids


async def _cleanup(conn, projeto_id, pesquisa_id):
    """Limpa em ordem: kw_staging → pesquisas → projetos."""
    await conn.execute(
        "DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id
    )
    await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)
    await conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_id)


@pytest.mark.asyncio
async def test_happy_no_filters(db_conn):
    """T1: seed 3 kws com volumes 300/200/100, GET sem filtros, assert total=3, primeiro item tem avg_monthly_searches=300."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn, n_kws=3, volumes=[300, 200, 100]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/projetos/{proj_id}/keywords")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        # Ordenados por avg_monthly_searches DESC NULLS LAST → primeiro deve ter 300
        assert body["items"][0]["avg_monthly_searches"] == 300
    finally:
        await _cleanup(db_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_combined_filters_status_kw_type(db_conn):
    """T2: seed 3 kws (2 approved+PAGINA_PRINCIPAL, 1 pending+PAGINA_GEO), GET ?status=approved&kw_type=PAGINA_PRINCIPAL, assert total=2."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn,
        n_kws=3,
        volumes=[300, 200, 100],
        statuses=["approved", "approved", "pending"],
        kw_types=["PAGINA_PRINCIPAL", "PAGINA_PRINCIPAL", "PAGINA_GEO"],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                f"/projetos/{proj_id}/keywords",
                params={"status": "approved", "kw_type": "PAGINA_PRINCIPAL"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        for item in body["items"]:
            assert item["status"] == "approved"
            assert item["kw_type"] == "PAGINA_PRINCIPAL"
    finally:
        await _cleanup(db_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_negation_kw_type_not_descarta(db_conn):
    """T3: seed 3 kws (1 DESCARTA + 2 PAGINA_GEO), GET ?kw_type=!DESCARTA, assert total=2, nenhum com kw_type=='DESCARTA'."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn,
        n_kws=3,
        volumes=[300, 200, 100],
        statuses=["pending", "pending", "pending"],
        kw_types=["DESCARTA", "PAGINA_GEO", "PAGINA_GEO"],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                f"/projetos/{proj_id}/keywords",
                params={"kw_type": "!DESCARTA"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        for item in body["items"]:
            assert item["kw_type"] != "DESCARTA"
    finally:
        await _cleanup(db_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_pagination_limit_offset(db_conn):
    """T4: seed 5 kws, GET ?limit=2&offset=1, assert total=5, len(items)==2."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn,
        n_kws=5,
        volumes=[500, 400, 300, 200, 100],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                f"/projetos/{proj_id}/keywords",
                params={"limit": 2, "offset": 1},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
    finally:
        await _cleanup(db_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_projeto_not_found_404():
    """T5: UUID válido inexistente → 404."""
    fake_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/projetos/{fake_id}/keywords")
    assert r.status_code == 404
    assert "Projeto" in r.json()["detail"]
