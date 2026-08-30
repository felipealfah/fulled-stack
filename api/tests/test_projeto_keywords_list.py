"""KWMGMT-05 — testes do endpoint GET /projetos/{id}/keywords.

Padrão test_bulk_intel.py: seed via asyncpg direto, invocação via ASGITransport.

## Fase 35 / D-02 — o seed atravessa os dois bancos
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

`projetos` e `pesquisas` continuam no Postgres da Stack (`db_conn`, `DATABASE_URL`);
`kw_staging` mora no schema `leadgen` do Supabase (`lg_conn`, `LEADGEN_DB_URL`).
Semear a keyword no banco errado passa **silenciosamente**: o endpoint lê o outro banco
e o teste confere uma linha que ninguém mais enxerga.

Pré-condições:
- Túnel VPS aberto (`bash Full_AIOS_STACK/vps_tunnel.sh -d`) — Postgres em localhost:5433.
- `LEADGEN_DB_URL` resolvido pelo conftest.py (Supavisor session pooler).
- AUTH_ENABLED=false (setado no conftest.py).

Rodar:
    cd Full_AIOS_STACK
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
    """Postgres da Stack — camada de decisão (`projetos`, `pesquisas`)."""
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    yield conn
    await conn.close()


@pytest.fixture
async def lg_conn():
    """Supabase, schema `leadgen` — camada pré-decisão (`kw_staging`).

    `search_path` espelha o do pool da app (`db_leadgen.get_lg_pool`), para que o SQL do
    seed continue dizendo `FROM kw_staging` sem prefixo de schema.
    """
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"}
    )
    yield conn
    await conn.close()


async def _seed_projeto_com_kws(
    conn, lg, n_kws=3, volumes=None, statuses=None, kw_types=None, papel="principal"
):
    """Cria projeto + pesquisa (Postgres) + N kw_staging (Supabase).

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
           VALUES ($1, $2, 'Brasília', 'classificado', $4, $3::uuid) RETURNING id""",
        f"Test-KwList-Pesq-{suffix}",
        f"nicho-kwlist-{suffix}",
        str(projeto_id),
        papel,
    )

    kw_ids = []
    for i in range(n_kws):
        vol = (volumes[i] if volumes and i < len(volumes) else (300 - i * 100))
        st = (statuses[i] if statuses and i < len(statuses) else "pending")
        kt = (kw_types[i] if kw_types and i < len(kw_types) else "PAGINA_PRINCIPAL")
        kwid = await lg.fetchval(
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


async def _cleanup(conn, lg, projeto_id, *pesquisa_ids):
    """Limpa em ordem: kw_staging (Supabase) → pesquisas → projetos (Postgres)."""
    for pesquisa_id in pesquisa_ids:
        await lg.execute(
            "DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id
        )
        await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)
    await conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_id)


@pytest.mark.asyncio
async def test_happy_no_filters(db_conn, lg_conn):
    """T1: seed 3 kws com volumes 300/200/100, GET sem filtros, assert total=3, primeiro item tem avg_monthly_searches=300."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn, lg_conn, n_kws=3, volumes=[300, 200, 100]
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
        await _cleanup(db_conn, lg_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_combined_filters_status_kw_type(db_conn, lg_conn):
    """T2: seed 3 kws (2 approved+PAGINA_PRINCIPAL, 1 pending+PAGINA_GEO), GET ?status=approved&kw_type=PAGINA_PRINCIPAL, assert total=2."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn,
        lg_conn,
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
        await _cleanup(db_conn, lg_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_negation_kw_type_not_descarta(db_conn, lg_conn):
    """T3: seed 3 kws (1 DESCARTA + 2 PAGINA_GEO), GET ?kw_type=!DESCARTA, assert total=2, nenhum com kw_type=='DESCARTA'."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn,
        lg_conn,
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
        await _cleanup(db_conn, lg_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_pagination_limit_offset(db_conn, lg_conn):
    """T4: seed 5 kws, GET ?limit=2&offset=1, assert total=5, len(items)==2."""
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(
        db_conn,
        lg_conn,
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
        await _cleanup(db_conn, lg_conn, proj_id, pesq_id)


@pytest.mark.asyncio
async def test_projeto_not_found_404():
    """T5: UUID válido inexistente → 404."""
    fake_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/projetos/{fake_id}/keywords")
    assert r.status_code == 404
    assert "Projeto" in r.json()["detail"]


@pytest.mark.asyncio
async def test_filtro_papel_continua_estreitando(db_conn, lg_conn):
    """Fase 35 — `papel` saiu do SQL do Supabase e virou filtro sobre as pesquisas.

    `papel` é coluna de `pesquisas` (Postgres); `kw_staging` (Supabase) não a tem. Se o
    recorte perder o filtro, o projeto devolve as keywords das DUAS pesquisas e o total
    dobra silenciosamente. Duas pesquisas do mesmo projeto, papéis diferentes, contagens
    diferentes — é o que separa "filtrou" de "não filtrou".
    """
    proj_id, pesq_principal, _ = await _seed_projeto_com_kws(
        db_conn, lg_conn, n_kws=2, volumes=[300, 200], papel="principal"
    )
    # Segunda pesquisa no MESMO projeto, com papel diferente e outra contagem.
    suffix = uuid.uuid4().hex[:8]
    pesq_servico = str(await db_conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'classificado', 'servico', $3::uuid) RETURNING id""",
        f"Test-KwList-Serv-{suffix}", f"nicho-kwlist-serv-{suffix}", proj_id,
    ))
    for i in range(3):
        await lg_conn.execute(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status, avg_monthly_searches)
               VALUES ($1::uuid, $2, 'SECAO', 'pending', $3)""",
            pesq_servico, f"kw-kwlist-serv-{suffix}-{i}", 100 + i,
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r_todos = await c.get(f"/projetos/{proj_id}/keywords")
            r_princ = await c.get(f"/projetos/{proj_id}/keywords", params={"papel": "principal"})
            r_serv = await c.get(f"/projetos/{proj_id}/keywords", params={"papel": "servico"})
            r_nada = await c.get(f"/projetos/{proj_id}/keywords", params={"papel": "inexistente"})

        assert r_todos.json()["total"] == 5, r_todos.text

        principal = r_princ.json()
        assert principal["total"] == 2, principal
        assert {i["papel"] for i in principal["items"]} == {"principal"}
        assert {i["pesquisa_id"] for i in principal["items"]} == {pesq_principal}
        # As colunas que vinham do JOIN chegam preenchidas, não nulas.
        assert all(i["nicho"] and i["pesquisa_status"] == "classificado"
                   for i in principal["items"])
        # O resumo respeita o filtro — é o contador das abas do Board.
        assert sum(principal["resumo"]["por_status"].values()) == 2

        servico = r_serv.json()
        assert servico["total"] == 3, servico
        assert {i["papel"] for i in servico["items"]} == {"servico"}

        vazio = r_nada.json()
        assert vazio == {"total": 0, "items": [],
                         "resumo": {"por_status": {}, "por_kw_type": {}}}, vazio
    finally:
        await _cleanup(db_conn, lg_conn, proj_id, pesq_principal, pesq_servico)


@pytest.mark.asyncio
async def test_pesquisa_id_malformado_422(db_conn, lg_conn):
    """`?pesquisa_id=nao-e-uuid` respondia **500** antes da Fase 35 (medido).

    O `except` do handler só reconhecia `invalid input syntax` (erro do servidor), mas
    com o cast `::uuid` quem rejeita é o asyncpg no bind — `invalid input for query
    argument ... (invalid UUID ...)`. Mesma classe de bug que os Plans 35-03/04/06
    corrigiram nos outros routers.
    """
    proj_id, pesq_id, _ = await _seed_projeto_com_kws(db_conn, lg_conn, n_kws=1)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                f"/projetos/{proj_id}/keywords", params={"pesquisa_id": "nao-e-uuid"}
            )
        assert r.status_code == 422, r.text
        assert "UUID" in r.json()["detail"]
    finally:
        await _cleanup(db_conn, lg_conn, proj_id, pesq_id)
