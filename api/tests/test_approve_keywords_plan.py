"""GATE-KW-01 — POST /projetos/{uuid}/keywords/approve + regressão do bug de projeto_id.

O bug de 2026-08-03: `approve-classified` filtrava pesquisas por `p.projeto_id`
(INT legado). `POST /pesquisas/` só popula `projeto_id_uuid`, então em todo projeto
criado pós-migração UUID o filtro casava zero linhas e o endpoint devolvia
HTTP 200 {"approved": 0} sem erro. As keywords ficavam presas em 'pending'.

O teste antigo (test_approve_classified.py) não pegou porque o fixture seedava
`projeto_id` INT explicitamente. Aqui os fixtures seedam pesquisas **só com UUID**
— exatamente o estado que a produção tinha.

## Fase 35 / D-06 — o Gate escreve nos DOIS bancos
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

`pesquisas` fica no Postgres da Stack (`db_conn`), `kw_staging` mora no schema `leadgen`
do Supabase (`lg_conn`). Semear a keyword no banco errado passa silenciosamente.

Pré-condições:
- Túnel VPS aberto (`bash Full_AIOS_STACK/vps_tunnel.sh -d`) — Postgres em localhost:5433.
- `LEADGEN_DB_URL` resolvido pelo conftest.py (Supavisor session pooler).
- Migration 032 aplicada.
- AUTH_ENABLED=false (setado no conftest.py).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_approve_keywords_plan.py -v
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

# UUID real do projeto MM Entulho no VPS (id_int_legado=8).
PROJETO_MM_UUID = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"

# Contrato de resposta do Gate — congelado contra o código pré-Fase 35 (SC-01).
CHAVES_APPROVE = {
    "approved", "rejected", "reclassified", "skipped_descarta",
    "pending_restantes", "pesquisas_atualizadas", "not_found", "invalid",
}


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
    """Postgres da Stack — camada de decisão (`projetos`, `pesquisas`)."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


@pytest.fixture
async def lg_conn():
    """Supabase, schema `leadgen` — camada pré-decisão (`kw_staging`)."""
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"}
    )
    yield conn
    await conn.close()


async def _seed_uuid_only(conn, lg, kws, status="classificado"):
    """Cria pesquisa vinculada APENAS por projeto_id_uuid (projeto_id INT = NULL).

    Esse é o estado real de produção que o bug original não enxergava.
    A pesquisa vai para o Postgres; as keywords, para o Supabase.
    Retorna (pesquisa_id, {keyword: kw_staging_id}).
    """
    suffix = uuid.uuid4().hex[:8]
    pid = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel,
                                  projeto_id, projeto_id_uuid)
           VALUES ('MM Entulho', $1, 'Brasília', $2, 'servico', NULL, $3::uuid)
           RETURNING id""",
        f"nicho-gate-{suffix}", status, PROJETO_MM_UUID,
    )
    ids = {}
    for kw, kw_type in kws:
        ids[kw] = await lg.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, $3, 'pending') RETURNING id""",
            str(pid), f"{kw}-{suffix}", kw_type,
        )
    return pid, ids


async def _cleanup(conn, lg, pesquisa_id):
    """Filhos no Supabase primeiro, pesquisa no Postgres depois.

    Recebe o `pesquisa_id` explícito (lição do Plan 35-05): redescobri-lo pelo projeto
    devolveria vazio sempre que o teste falhasse depois de a pesquisa já ter sumido.
    """
    await lg.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", str(pesquisa_id))
    await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


async def _status_of(lg, kw_id):
    return await lg.fetchval("SELECT status FROM kw_staging WHERE id = $1", kw_id)


@pytest.mark.asyncio
async def test_regressao_pesquisa_sem_projeto_id_int(db_conn, lg_conn):
    """REGRESSÃO do bug: pesquisa só com UUID deve ser alcançada pelo approve.

    Antes do fix este teste falharia com approved=0.
    """
    pid, ids = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-reg-a", "SECAO"), ("kw-reg-b", "PAGINA_GEO")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r.status_code == 200, r.text
        assert await _status_of(lg_conn, ids["kw-reg-a"]) == "approved"
        assert await _status_of(lg_conn, ids["kw-reg-b"]) == "approved"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_approve_classified_tambem_alcanca_uuid_only(db_conn, lg_conn):
    """O endpoint legado herdou o mesmo fix — scripts antigos voltam a funcionar."""
    pid, ids = await _seed_uuid_only(db_conn, lg_conn, [("kw-legacy", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
        assert r.status_code == 200, r.text
        assert r.json()["approved"] >= 1
        assert await _status_of(lg_conn, ids["kw-legacy"]) == "approved"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_approve_ids_seleciona_apenas_marcadas(db_conn, lg_conn):
    """Seleção explícita: só o id enviado sobe para approved."""
    pid, ids = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-sel-1", "SECAO"), ("kw-sel-2", "SECAO")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_ids": [ids["kw-sel-1"]]},
            )
        assert r.status_code == 200, r.text
        assert r.json()["approved"] == 1
        assert await _status_of(lg_conn, ids["kw-sel-1"]) == "approved"
        assert await _status_of(lg_conn, ids["kw-sel-2"]) == "pending"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_reclassify_antes_de_aprovar(db_conn, lg_conn):
    """DESCARTA reclassificada para SECAO no mesmo request deve ser aprovada."""
    pid, ids = await _seed_uuid_only(db_conn, lg_conn, [("kw-recl", "DESCARTA")])
    kid = ids["kw-recl"]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={
                    "reclassify": [{"keyword_id": kid, "kw_type": "SECAO"}],
                    "approve_ids": [kid],
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reclassified"] == 1
        assert body["approved"] == 1
        assert body["skipped_descarta"] == 0
        row = await lg_conn.fetchrow(
            "SELECT kw_type, status FROM kw_staging WHERE id = $1", kid
        )
        assert row["kw_type"] == "SECAO"
        assert row["status"] == "approved"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_descarta_nao_e_aprovada_por_engano(db_conn, lg_conn):
    """approve_ids contendo DESCARTA → conta em skipped_descarta, continua pending."""
    pid, ids = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-desc", "DESCARTA"), ("kw-ok", "SECAO")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_ids": [ids["kw-desc"], ids["kw-ok"]]},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] == 1
        assert body["skipped_descarta"] == 1
        assert await _status_of(lg_conn, ids["kw-desc"]) == "pending"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_reject_marca_rejected(db_conn, lg_conn):
    pid, ids = await _seed_uuid_only(db_conn, lg_conn, [("kw-rej", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"reject_ids": [ids["kw-rej"]]},
            )
        assert r.status_code == 200, r.text
        assert r.json()["rejected"] == 1
        assert await _status_of(lg_conn, ids["kw-rej"]) == "rejected"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_id_de_outro_projeto_vai_para_not_found(db_conn, lg_conn):
    """ID que não pertence ao projeto não quebra o lote — volta em not_found."""
    pid, ids = await _seed_uuid_only(db_conn, lg_conn, [("kw-own", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_ids": [ids["kw-own"], 999_999_999]},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] == 1
        assert 999_999_999 in body["not_found"]
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_kw_type_invalido_vai_para_invalid(db_conn, lg_conn):
    pid, ids = await _seed_uuid_only(db_conn, lg_conn, [("kw-inv", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"reclassify": [{"keyword_id": ids["kw-inv"], "kw_type": "BANANA"}]},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reclassified"] == 0
        assert len(body["invalid"]) == 1
        assert "BANANA" in body["invalid"][0]["reason"]
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_pesquisa_sobe_para_aprovado(db_conn, lg_conn):
    """Aprovar keywords de uma pesquisa 'classificado' promove a pesquisa."""
    pid, _ = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-prom", "SECAO")], status="classificado"
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r.status_code == 200, r.text
        status = await db_conn.fetchval("SELECT status FROM pesquisas WHERE id = $1::uuid", pid)
        assert status == "aprovado"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_idempotente(db_conn, lg_conn):
    """Rerun não reaprova nada e zera o saldo de pendentes desta pesquisa."""
    pid, _ = await _seed_uuid_only(db_conn, lg_conn, [("kw-idem", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
            assert r1.json()["approved"] >= 1
            r2 = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r2.status_code == 200, r2.text
        assert r2.json()["approved"] == 0
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_projeto_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/projetos/{uuid.uuid4()}/keywords/approve",
            json={"approve_all_non_descarta": True},
        )
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_listagem_traz_resumo_e_filtro_negado(db_conn, lg_conn):
    """GET com kw_type='!DESCARTA' e status='pending' alimenta o Passo 0 do seo-architect."""
    pid, _ = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-list-1", "SECAO"), ("kw-list-2", "DESCARTA")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                f"/projetos/{PROJETO_MM_UUID}/keywords",
                params={"status": "pending", "kw_type": "!DESCARTA", "limit": 1},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1
        assert "por_status" in body["resumo"]
        assert "DESCARTA" not in body["resumo"]["por_kw_type"]
    finally:
        await _cleanup(db_conn, lg_conn, pid)


# ───────────────────────── Fase 35 / D-06 ─────────────────────────


@pytest.mark.asyncio
async def test_caminho_feliz_tem_exatamente_as_8_chaves(db_conn, lg_conn):
    """SC-01 — o caminho feliz não ganha `aviso` nem nenhuma outra chave nova.

    O campo `aviso` só existe quando o bloco B falha. Se ele vazar para a resposta
    normal, o dashboard e os agentes passam a ver um contrato diferente do de sempre.
    """
    pid, _ = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-8k-a", "SECAO"), ("kw-8k-b", "DESCARTA")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r_all = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
            r_vazio = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve", json={}
            )
        for r in (r_all, r_vazio):
            assert r.status_code == 200, r.text
            assert set(r.json()) == CHAVES_APPROVE, sorted(set(r.json()) ^ CHAVES_APPROVE)
            assert "aviso" not in r.json()
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_falha_do_bloco_B_responde_200_com_aviso_e_estado_conservador(
    db_conn, lg_conn, monkeypatch
):
    """SC-03 — o coração do plano: falha parcial na direção conservadora.

    Simula o Postgres caindo **depois** do commit no Supabase, envenenando o
    `pool.acquire` só a partir da segunda aquisição (a primeira é o bloco 0). O que se
    exige do resultado:

      1. HTTP **200**, nunca um 500 mudo — o clique teve efeito e o Board precisa saber;
      2. `pesquisas_atualizadas` vazio e um `aviso` em pt-BR pedindo a reexecução;
      3. estado conservador: `kw_staging` **approved** e `pesquisas` ainda
         **classificado** — o pipeline não avança, jamais avança com dado errado;
      4. reexecutar o mesmo endpoint converge, com `approved: 0` (bloco A vira no-op).
    """
    pid, ids = await _seed_uuid_only(db_conn, lg_conn, [("kw-falha-b", "SECAO")])
    try:
        import db as db_mod
        from routers import keywords as kw_module

        pool_real = await db_mod.get_pool()

        class PoolQueCaiDepoisDoBloco0:
            """`Pool.acquire` do asyncpg é read-only — daí o proxy em vez de monkeypatch.

            A 1ª aquisição (bloco 0) passa; da 2ª em diante (bloco B) estoura. É
            exatamente a janela entre o commit do Supabase e a escrita no Postgres.
            """

            def __init__(self, real):
                self._real = real
                self.n = 0

            def acquire(self, *a, **kw):
                self.n += 1
                if self.n >= 2:
                    raise ConnectionError("Postgres indisponível (simulado)")
                return self._real.acquire(*a, **kw)

        proxy = PoolQueCaiDepoisDoBloco0(pool_real)

        async def _get_pool_quebrado():
            return proxy

        monkeypatch.setattr(kw_module, "get_pool", _get_pool_quebrado)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] >= 1, body
        assert body["pesquisas_atualizadas"] == [], body
        assert "aviso" in body, body
        assert "reexecute" in body["aviso"].lower(), body["aviso"]
        assert set(body) == CHAVES_APPROVE | {"aviso"}

        # Estado conservador nos dois bancos.
        assert await _status_of(lg_conn, ids["kw-falha-b"]) == "approved"
        assert await db_conn.fetchval(
            "SELECT status FROM pesquisas WHERE id = $1::uuid", pid
        ) == "classificado"

        # Cura: o Postgres volta e a reexecução converge sem duplicar efeito.
        monkeypatch.undo()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r2 = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["approved"] == 0, body2          # bloco A é no-op
        assert set(body2) == CHAVES_APPROVE, sorted(set(body2) ^ CHAVES_APPROVE)
        assert str(pid) in body2["pesquisas_atualizadas"], body2
        assert await db_conn.fetchval(
            "SELECT status FROM pesquisas WHERE id = $1::uuid", pid
        ) == "aprovado"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_bloco_A_e_atomico(db_conn, lg_conn):
    """Os passos 1-3 vivem numa transação só: kw_type inválido não impede o approve.

    E o inverso do que a transação protege: se a instrução de approve estourasse, o
    reclassify já aplicado teria de voltar atrás. Aqui o que se observa é a metade
    verificável sem injetar erro — reclassify e approve chegam juntos ao banco.
    """
    pid, ids = await _seed_uuid_only(
        db_conn, lg_conn, [("kw-atom-1", "DESCARTA"), ("kw-atom-2", "SECAO")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={
                    "reclassify": [
                        {"keyword_id": ids["kw-atom-1"], "kw_type": "PAGINA_GEO"},
                        {"keyword_id": ids["kw-atom-2"], "kw_type": "BANANA"},
                    ],
                    "approve_all_non_descarta": True,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reclassified"] == 1, body
        assert len(body["invalid"]) == 1, body
        linhas = await lg_conn.fetch(
            "SELECT id, kw_type, status FROM kw_staging WHERE pesquisa_id = $1::uuid",
            str(pid),
        )
        por_id = {r["id"]: dict(r) for r in linhas}
        # A reclassificada saiu de DESCARTA e foi aprovada no mesmo request.
        assert por_id[ids["kw-atom-1"]]["kw_type"] == "PAGINA_GEO"
        assert por_id[ids["kw-atom-1"]]["status"] == "approved"
        assert por_id[ids["kw-atom-2"]]["status"] == "approved"
    finally:
        await _cleanup(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_contagens_incluem_pesquisas_nao_revisaveis(db_conn, lg_conn):
    """`skipped_descarta` e `pending_restantes` contam sobre TODAS as pesquisas.

    O SQL original filtrava por status de pesquisa no UPDATE, mas **não** nessas duas
    contagens. Se o recorte usar a lista de pesquisas revisáveis nas quatro consultas,
    o número que o Board lê encolhe em silêncio. Aqui a pesquisa em `pending_review`
    (não revisável) tem 1 DESCARTA e 1 pendente que precisam continuar aparecendo.
    """
    pid_ok, _ = await _seed_uuid_only(db_conn, lg_conn, [("kw-conta-ok", "SECAO")])
    pid_fora, ids_fora = await _seed_uuid_only(
        db_conn, lg_conn,
        [("kw-conta-desc", "DESCARTA"), ("kw-conta-pend", "SECAO")],
        status="pending_review",
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        # A pesquisa não revisável NÃO é tocada pela aprovação...
        assert await _status_of(lg_conn, ids_fora["kw-conta-pend"]) == "pending"
        # ...mas entra nas duas contagens de saldo.
        assert body["skipped_descarta"] >= 1, body
        assert body["pending_restantes"] >= 1, body
    finally:
        await _cleanup(db_conn, lg_conn, pid_ok)
        await _cleanup(db_conn, lg_conn, pid_fora)
