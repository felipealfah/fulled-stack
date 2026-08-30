"""Plan 32-03 — DELETE /pesquisas/{id} com guard de projeto em produção (KWMGMT-03).

Testes cobrem:
- Delete normal (projeto rascunho) — sem guard
- Guard ativado quando projeto em produção (status=deploy) sem force
- Force=true ignora guard
- UUID inexistente → 404
- Delete limpa kw_staging e as demais tabelas migradas, sem deixar órfãos

## Fase 35 / D-06 — o cascade do banco não existe mais
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Antes da fase, `DELETE FROM pesquisas` disparava as FKs de 6 tabelas. Todas as 6 mudaram
para o Supabase e não existe FK atravessando a fronteira dos bancos: se o handler não
compensar isso explicitamente, o delete passa a deixar keywords órfãs e páginas apontando
para uma pesquisa que não existe mais. Este arquivo trava esse comportamento.

As 6 foram conferidas no catálogo do Postgres vivo (`pg_constraint` com
`confrelid = 'pesquisas'`), não em documentação — foi assim que o Plan 35-04 descobriu que
a lista dele estava incompleta:

  confdeltype='c'/'a' → a linha some:   kw_staging, kw_classification_overrides,
                                        scorecard_overrides, kw_scorecard
  confdeltype='n'     → a linha fica,   content_pages, projeto_seo_plan_pages
                        só perde o vínculo

`agent_executions.pesquisa_id` e `projetos.pesquisa_id_atual` NÃO entram aqui: continuam no
Postgres da Stack e já eram tratadas à mão pelo handler.

⚠️ Fase 35 / T-35-03: este arquivo fixava `DATABASE_URL` com a senha de produção em texto
claro, apontando para `localhost:5432`. Além do segredo versionado, a atribuição direta em
`os.environ` sobrescrevia a resolução do `conftest.py` para a sessão inteira do pytest —
qualquer outro arquivo rodado junto herdava a DSN errada. As duas DSNs vêm do conftest.

Pré-condições:
- Túnel VPS Postgres em localhost:5433 (`bash vps_tunnel.sh -d`).
- `LEADGEN_DB_URL` no `.env` apontando para o Supavisor session pooler.
- AUTH_ENABLED=false (o conftest resolve as três coisas).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_pesquisa_delete_guard.py -v
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


# Espelha _TABELAS_APAGAR / _TABELAS_NULIFICAR de routers/kw_mgmt.py.
TABELAS_APAGAR = (
    "kw_classification_overrides",
    "scorecard_overrides",
    "kw_scorecard",
    "kw_staging",
)
TABELAS_NULIFICAR = (
    "content_pages",
    "projeto_seo_plan_pages",
)


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Fecha o pool antes/depois de cada teste.

    O pool do Supabase (`db_leadgen._lg_pool`) é zerado pela fixture autouse do conftest.
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
async def db_conn():
    """Postgres da Stack — `pesquisas`, `projetos` e `agent_executions` não migraram."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


@pytest.fixture
async def lg_conn():
    """Supabase, schema `leadgen` — onde vivem as 6 tabelas que perderam a FK."""
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"},
    )
    yield conn
    await conn.close()


async def _seed_projeto(conn, status: str = "research") -> tuple[str, int]:
    """Cria um projeto no Postgres. Retorna (uuid_str, id_int_legado).

    O id inteiro é necessário porque `content_pages.projeto_id` e
    `projeto_seo_plan.projeto_id` no Supabase ainda são INTEGER NOT NULL.
    """
    suffix = uuid.uuid4().hex[:8]
    row = await conn.fetchrow(
        """INSERT INTO projetos (projeto_nome, nicho, cidade, status)
           VALUES ($1, $2, 'Brasília', $3) RETURNING id, id_int_legado""",
        f"Test-Delete-Guard-{suffix}",
        f"nicho-delete-{suffix}",
        status,
    )
    return str(row["id"]), row["id_int_legado"]


async def _seed_pesquisa(
    db_conn, lg_conn, projeto_id_uuid: str | None = None, n_kws: int = 0,
) -> tuple[str, list[int]]:
    """Cria pesquisa (Postgres) + n_kws keywords (Supabase). Retorna (pid, [kw_ids])."""
    suffix = uuid.uuid4().hex[:8]
    pid = await db_conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'pending_review', $3::uuid) RETURNING id""",
        f"Test-DeletePesq-{suffix}",
        f"nicho-pesq-{suffix}",
        projeto_id_uuid,
    )
    kw_ids = []
    if n_kws:
        rows = await lg_conn.fetch(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               SELECT $1::uuid, $2 || i::text, 'PAGINA_PRINCIPAL', 'pending'
                 FROM generate_series(0, $3::int - 1) AS g(i)
               RETURNING id""",
            pid, f"kw-del-{suffix}-", n_kws,
        )
        kw_ids = [r["id"] for r in rows]
    return str(pid), kw_ids


async def _semear_dependentes(
    lg_conn, pesquisa_id: str, projeto_id_uuid: str, projeto_id_int: int,
) -> None:
    """Uma linha em cada tabela migrada que referencia a pesquisa (além de kw_staging)."""
    sfx = uuid.uuid4().hex[:8]
    await lg_conn.execute(
        """INSERT INTO kw_classification_overrides (pesquisa_id, keyword, classificacao_humana)
           VALUES ($1::uuid, $2, 'SECAO')""",
        pesquisa_id, f"kw-cls-{sfx}",
    )
    await lg_conn.execute(
        """INSERT INTO scorecard_overrides (pesquisa_id, decisao_agente, decisao_humana, motivo)
           VALUES ($1::uuid, 'NO-GO', 'GO', $2)""",
        pesquisa_id, f"motivo-{sfx}",
    )
    await lg_conn.execute(
        """INSERT INTO kw_scorecard (pesquisa_id, scorecard_json, decisao_final)
           VALUES ($1::uuid, '{}'::jsonb, 'GO')""",
        pesquisa_id,
    )
    await lg_conn.execute(
        """INSERT INTO content_pages (projeto_id, projeto_id_uuid, pesquisa_id,
                                      page_slug, page_type, status)
           VALUES ($1, $2::uuid, $3::uuid, $4, 'home', 'gerado')""",
        projeto_id_int, projeto_id_uuid, pesquisa_id, f"pagina-del-{sfx}",
    )
    plan_id = await lg_conn.fetchval(
        """INSERT INTO projeto_seo_plan (projeto_id, projeto_id_uuid, status)
           VALUES ($1, $2::uuid, 'rascunho') RETURNING id""",
        projeto_id_int, projeto_id_uuid,
    )
    await lg_conn.execute(
        """INSERT INTO projeto_seo_plan_pages (plan_id, pesquisa_id, papel)
           VALUES ($1, $2::uuid, 'principal')""",
        plan_id, pesquisa_id,
    )


async def _contar(lg_conn, pesquisa_id: str) -> dict[str, int]:
    """Quantas linhas cada tabela migrada ainda referencia para esta pesquisa."""
    return {
        tabela: await lg_conn.fetchval(
            f"SELECT count(*) FROM {tabela} WHERE pesquisa_id = $1::uuid",  # noqa: S608
            pesquisa_id,
        )
        for tabela in TABELAS_APAGAR + TABELAS_NULIFICAR
    }


async def _cleanup_projeto(db_conn, lg_conn, projeto_id: str):
    """Teardown incondicional — nos DOIS bancos, mesmo se o teste falhou."""
    pesquisas = [
        str(r["id"])
        for r in await db_conn.fetch(
            "SELECT id FROM pesquisas WHERE projeto_id_uuid = $1::uuid", projeto_id,
        )
    ]
    for pid in pesquisas:
        for tabela in TABELAS_APAGAR:
            await lg_conn.execute(
                f"DELETE FROM {tabela} WHERE pesquisa_id = $1::uuid", pid,  # noqa: S608
            )
        for tabela in TABELAS_NULIFICAR:
            await lg_conn.execute(
                f"UPDATE {tabela} SET pesquisa_id = NULL WHERE pesquisa_id = $1::uuid",  # noqa: S608
                pid,
            )
    await lg_conn.execute(
        "DELETE FROM content_pages WHERE projeto_id_uuid = $1::uuid", projeto_id,
    )
    # projeto_seo_plan_pages some junto: a FK plan_id -> projeto_seo_plan continua sendo
    # cascade de banco de verdade (as duas vivem dentro do schema `leadgen`).
    await lg_conn.execute(
        "DELETE FROM projeto_seo_plan WHERE projeto_id_uuid = $1::uuid", projeto_id,
    )
    await db_conn.execute(
        "UPDATE projetos SET pesquisa_id_atual = NULL WHERE id = $1::uuid", projeto_id,
    )
    await db_conn.execute(
        "DELETE FROM pesquisas WHERE projeto_id_uuid = $1::uuid", projeto_id,
    )
    await db_conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_id)


@pytest.mark.asyncio
async def test_delete_projeto_rascunho_hard(db_conn, lg_conn):
    """T1: projeto status='research' + pesquisa + 3 kws → DELETE → 200, deleted_keywords=3."""
    proj_id, proj_int = await _seed_projeto(db_conn, status="research")
    pid, kw_ids = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=3)
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
        await _cleanup_projeto(db_conn, lg_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_guard_projeto_deploy(db_conn, lg_conn):
    """T2: projeto status='deploy' + pesquisa → DELETE sem force → 409, pesquisa ainda existe."""
    proj_id, proj_int = await _seed_projeto(db_conn, status="deploy")
    pid, _ = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=1)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 409, r.text
        assert "produção" in r.json()["detail"] or "deploy" in r.json()["detail"]
        # Pesquisa ainda deve existir
        row = await db_conn.fetchrow("SELECT id FROM pesquisas WHERE id = $1::uuid", pid)
        assert row is not None, "Pesquisa foi deletada mesmo com guard ativo"
    finally:
        await _cleanup_projeto(db_conn, lg_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_guard_nao_escreve_em_nenhum_banco(db_conn, lg_conn):
    """T2b (D-06): a guarda 409 é avaliada ANTES de qualquer escrita, nos dois bancos.

    Com o handler em 3 etapas, a ordem deixou de ser garantida por uma transação única.
    Se alguém mover a guarda para depois do passo 2, este teste falha: as keywords já
    teriam sido apagadas no Supabase enquanto a resposta diz 409 ('nada foi feito').
    """
    proj_id, proj_int = await _seed_projeto(db_conn, status="monetizacao")
    pid, _ = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=3)
    try:
        await _semear_dependentes(lg_conn, pid, proj_id, proj_int)
        antes = await _contar(lg_conn, pid)
        assert antes["kw_staging"] == 3, antes
        assert all(v >= 1 for v in antes.values()), f"seed incompleto: {antes}"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 409, r.text

        # Supabase: nada mudou.
        depois = await _contar(lg_conn, pid)
        assert depois == antes, f"a guarda 409 escreveu no Supabase: {antes} -> {depois}"
        # Postgres: nada mudou.
        assert await db_conn.fetchval(
            "SELECT count(*) FROM pesquisas WHERE id = $1::uuid", pid,
        ) == 1
    finally:
        await _cleanup_projeto(db_conn, lg_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_force_hard_over_deploy(db_conn, lg_conn):
    """T3: projeto status='deploy' + pesquisa → DELETE ?force=true → 200, pesquisa sumiu."""
    proj_id, proj_int = await _seed_projeto(db_conn, status="deploy")
    pid, _ = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=0)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}?force=true")
        assert r.status_code == 200, r.text
        # Pesquisa não deve mais existir
        row = await db_conn.fetchrow("SELECT id FROM pesquisas WHERE id = $1::uuid", pid)
        assert row is None, "Pesquisa ainda existe após DELETE force=true"
    finally:
        await _cleanup_projeto(db_conn, lg_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_pesquisa_not_found():
    """T4: DELETE UUID inexistente → 404."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(f"/pesquisas/{fake}")
    assert r.status_code == 404, r.text
    assert "Pesquisa" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_pesquisa_uuid_malformado_422():
    """T4b: path param que não é UUID → 422 pt-BR, e não 500."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/pesquisas/nao-e-uuid")
    assert r.status_code == 422, r.text
    assert "UUID" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_limpa_kws(db_conn, lg_conn):
    """T5: seed + 3 kws → DELETE → COUNT kw_staging == 0 para essa pesquisa."""
    proj_id, proj_int = await _seed_projeto(db_conn, status="research")
    pid, kw_ids = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=3)
    try:
        # Confirmar que kws existem antes
        count_before = await lg_conn.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid", pid
        )
        assert count_before == 3

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 200, r.text

        # kw_staging deve estar limpa — agora por limpeza explícita, não por CASCADE
        count_after = await lg_conn.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE id = ANY($1::int[])", kw_ids
        )
        assert count_after == 0, f"Ainda existem {count_after} kws após DELETE"
    finally:
        await _cleanup_projeto(db_conn, lg_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_nao_deixa_orfaos_nas_tabelas_migradas(db_conn, lg_conn):
    """T6 (D-06): depois do DELETE, nenhuma das 6 tabelas migradas referencia a pesquisa.

    É a regressão do cascade perdido. Comentar qualquer entrada de `_TABELAS_APAGAR` ou
    `_TABELAS_NULIFICAR` em `routers/kw_mgmt.py` faz este teste falhar, nomeando a tabela.
    """
    proj_id, proj_int = await _seed_projeto(db_conn, status="research")
    pid, _ = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=2)
    try:
        await _semear_dependentes(lg_conn, pid, proj_id, proj_int)

        # O seed precisa ter funcionado — senão o teste passaria por vacuidade.
        antes = await _contar(lg_conn, pid)
        assert all(v >= 1 for v in antes.values()), f"seed incompleto: {antes}"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 200, r.text
        assert r.json()["deleted_keywords"] == 2, r.json()

        depois = await _contar(lg_conn, pid)
        orfas = {t: n for t, n in depois.items() if n != 0}
        assert not orfas, f"órfãos deixados no Supabase: {orfas}"

        # `content_pages` é SET NULL, não DELETE: a página tem de SOBREVIVER sem o vínculo.
        # Apagá-la seria destruir conteúdo publicado — divergindo do comportamento antigo.
        sobreviventes = await lg_conn.fetchval(
            """SELECT count(*) FROM content_pages
                WHERE projeto_id_uuid = $1::uuid AND pesquisa_id IS NULL""",
            proj_id,
        )
        assert sobreviventes == 1, f"content_pages foi apagada em vez de nulificada ({sobreviventes})"
    finally:
        await _cleanup_projeto(db_conn, lg_conn, proj_id)


@pytest.mark.asyncio
async def test_delete_idempotente_apos_falha_parcial(db_conn, lg_conn):
    """T7: reexecutar o DELETE converge — os filhos já apagados viram no-op.

    É a garantia que torna a ordem filhos-primeiro segura: se o passo do Postgres falhar
    depois do passo do Supabase, a pesquisa sobrevive sem keywords e um novo DELETE
    conclui. Aqui simulamos esse estado apagando os filhos à mão antes de chamar.
    """
    proj_id, proj_int = await _seed_projeto(db_conn, status="research")
    pid, _ = await _seed_pesquisa(db_conn, lg_conn, projeto_id_uuid=proj_id, n_kws=2)
    try:
        for tabela in TABELAS_APAGAR:
            await lg_conn.execute(
                f"DELETE FROM {tabela} WHERE pesquisa_id = $1::uuid", pid,  # noqa: S608
            )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.delete(f"/pesquisas/{pid}")
        assert r.status_code == 200, r.text
        assert r.json()["deleted_keywords"] == 0, r.json()
        assert await db_conn.fetchval(
            "SELECT count(*) FROM pesquisas WHERE id = $1::uuid", pid,
        ) == 0
    finally:
        await _cleanup_projeto(db_conn, lg_conn, proj_id)
