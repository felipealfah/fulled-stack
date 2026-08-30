"""Fase 35 / D-06 — DELETE /projetos/{uuid} não pode deixar órfãos no Supabase.

ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Antes da fase, um `DELETE FROM projetos` disparava 6 `ON DELETE CASCADE` do banco. As 6
tabelas mudaram para o Supabase e não existe FK atravessando a fronteira dos bancos: se o
handler não apagar essas linhas explicitamente, o delete passa a deixar lixo invisível —
o tipo de defeito que só aparece meses depois como dado fantasma. Este arquivo trava esse
comportamento.

As 6 foram conferidas no catálogo do Postgres vivo (`pg_constraint.confdeltype='c'` com
`confrelid = 'projetos'`), não em documentação: `competitor_audits`, `content_pages`,
`projeto_geo_targets`, `projeto_seo_plan`, `rank_intel_overrides` e `backlink_intel`.

Não são testadas aqui `projeto_seo_plan_pages` e `projeto_seo_plan_pages_intel`: as FKs
delas apontam para dentro do próprio schema `leadgen` e continuam sendo cascade de banco.

Pré-condições:
- Túnel VPS Postgres em localhost:5433 (`bash vps_tunnel.sh -d`).
- `LEADGEN_DB_URL` no `.env` apontando para o Supavisor session pooler.
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_projeto_delete_orfaos.py -v
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


# (tabela, coluna que referencia o projeto). `backlink_intel` usa `projeto_id` — as outras
# cinco usam `projeto_id_uuid`. Espelha _TABELAS_CASCADE_PERDIDO de routers/projetos.py.
TABELAS_ESPERADAS = (
    ("competitor_audits", "projeto_id_uuid"),
    ("content_pages", "projeto_id_uuid"),
    ("projeto_geo_targets", "projeto_id_uuid"),
    ("projeto_seo_plan", "projeto_id_uuid"),
    ("rank_intel_overrides", "projeto_id_uuid"),
    ("backlink_intel", "projeto_id"),
)


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
async def pg_conn():
    """Postgres da Stack — `projetos` é camada de decisão e não migrou."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


@pytest.fixture
async def lg_conn():
    """Supabase, schema `leadgen` — onde vivem as 6 tabelas que perderam o cascade."""
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"},
    )
    yield conn
    await conn.close()


async def _criar_projeto(pg_conn) -> tuple[str, int]:
    """Cria um projeto descartável no Postgres. Retorna (uuid_str, id_int_legado)."""
    sfx = uuid.uuid4().hex[:8]
    row = await pg_conn.fetchrow(
        """INSERT INTO projetos (projeto_nome, nicho, cidade, status, tipo)
           VALUES ($1, $2, 'Brasília', 'research', 'rank_rent')
           RETURNING id, id_int_legado""",
        f"Test-Delete-Orfaos-{sfx}", f"nicho-orfaos-{sfx}",
    )
    return str(row["id"]), row["id_int_legado"]


async def _semear_filhos(lg_conn, pid_uuid: str, pid_int: int) -> None:
    """Uma linha em cada uma das 6 tabelas, referenciando o projeto."""
    await lg_conn.execute(
        """INSERT INTO competitor_audits (projeto_id, projeto_id_uuid, slug)
           VALUES ($1, $2::uuid, 'slug-orfaos')""",
        pid_int, pid_uuid,
    )
    await lg_conn.execute(
        """INSERT INTO content_pages (projeto_id, projeto_id_uuid, page_slug, page_type, status)
           VALUES ($1, $2::uuid, 'pagina-orfaos', 'home', 'gerado')""",
        pid_int, pid_uuid,
    )
    await lg_conn.execute(
        """INSERT INTO projeto_geo_targets (projeto_id, projeto_id_uuid, nome, tipo)
           VALUES ($1, $2::uuid, 'Bairro Órfão', 'bairro')""",
        pid_int, pid_uuid,
    )
    await lg_conn.execute(
        """INSERT INTO projeto_seo_plan (projeto_id, projeto_id_uuid, status)
           VALUES ($1, $2::uuid, 'rascunho')""",
        pid_int, pid_uuid,
    )
    await lg_conn.execute(
        """INSERT INTO rank_intel_overrides (projeto_id, projeto_id_uuid, keyword, action)
           VALUES ($1, $2::uuid, 'kw-orfaos', 'block')""",
        pid_int, pid_uuid,
    )
    await lg_conn.execute(
        """INSERT INTO backlink_intel (projeto_id, slug) VALUES ($1::uuid, 'slug-orfaos')""",
        pid_uuid,
    )


async def _contar_filhos(lg_conn, pid_uuid: str) -> dict[str, int]:
    """Quantas linhas cada tabela ainda tem para este projeto."""
    return {
        tabela: await lg_conn.fetchval(
            f"SELECT count(*) FROM {tabela} WHERE {coluna} = $1::uuid",  # noqa: S608
            pid_uuid,
        )
        for tabela, coluna in TABELAS_ESPERADAS
    }


async def _limpar(pg_conn, lg_conn, pid_uuid: str) -> None:
    """Teardown incondicional — remove tudo que o teste criou, mesmo se ele falhou."""
    for tabela, coluna in TABELAS_ESPERADAS:
        await lg_conn.execute(
            f"DELETE FROM {tabela} WHERE {coluna} = $1::uuid", pid_uuid,  # noqa: S608
        )
    await pg_conn.execute(
        "UPDATE pesquisas SET projeto_id_uuid = NULL WHERE projeto_id_uuid = $1::uuid", pid_uuid,
    )
    await pg_conn.execute("DELETE FROM projetos WHERE id = $1::uuid", pid_uuid)


@pytest.mark.asyncio
async def test_delete_projeto_nao_deixa_orfaos(pg_conn, lg_conn):
    """T1 (D-06): DELETE apaga o projeto E as 6 tabelas que perderam o cascade."""
    pid_uuid, pid_int = await _criar_projeto(pg_conn)
    try:
        await _semear_filhos(lg_conn, pid_uuid, pid_int)

        # O seed precisa ter funcionado — senão o teste passaria por vacuidade.
        antes = await _contar_filhos(lg_conn, pid_uuid)
        assert all(v == 1 for v in antes.values()), f"seed incompleto: {antes}"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/projetos/{pid_uuid}")
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # (b) o projeto sumiu do Postgres
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM projetos WHERE id = $1::uuid", pid_uuid,
        ) == 0

        # (c) nenhuma linha órfã nas 6 tabelas do Supabase
        depois = await _contar_filhos(lg_conn, pid_uuid)
        orfas = {t: n for t, n in depois.items() if n != 0}
        assert not orfas, f"órfãos deixados no Supabase: {orfas}"
    finally:
        await _limpar(pg_conn, lg_conn, pid_uuid)


@pytest.mark.asyncio
async def test_delete_projeto_idempotente_apos_falha_parcial(pg_conn, lg_conn):
    """T2: reexecutar o DELETE converge — os filhos já apagados viram no-op.

    É a garantia que torna a ordem filhos-primeiro segura: se o passo do Postgres falhar
    depois do passo do Supabase, o projeto sobrevive sem filhos e um novo DELETE conclui.
    Aqui simulamos esse estado apagando os filhos à mão antes de chamar o endpoint.
    """
    pid_uuid, pid_int = await _criar_projeto(pg_conn)
    try:
        await _semear_filhos(lg_conn, pid_uuid, pid_int)
        for tabela, coluna in TABELAS_ESPERADAS:
            await lg_conn.execute(
                f"DELETE FROM {tabela} WHERE {coluna} = $1::uuid", pid_uuid,  # noqa: S608
            )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/projetos/{pid_uuid}")
        assert r.status_code == 200, r.text
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM projetos WHERE id = $1::uuid", pid_uuid,
        ) == 0
    finally:
        await _limpar(pg_conn, lg_conn, pid_uuid)


@pytest.mark.asyncio
async def test_delete_projeto_inexistente_404():
    """T3: UUID válido que não existe → 404 em pt-BR, sem tocar no Supabase."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(f"/projetos/{uuid.uuid4()}")
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_projeto_uuid_malformado_422():
    """T4: path param que não é UUID → 422 em pt-BR.

    Antes da Fase 35 este caminho estourava `DataError` não tratado (500) porque o
    handler comparava `id = $1` sem cast e sem tratamento — mesmo bug que o Plan 35-03
    corrigiu em geo_targets.py e overrides.py.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/projetos/nao-e-uuid")
    assert r.status_code == 422, r.text
    assert "UUID" in r.json()["detail"]
