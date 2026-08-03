"""GATE-KW-01 — POST /projetos/{uuid}/keywords/approve + regressão do bug de projeto_id.

O bug de 2026-08-03: `approve-classified` filtrava pesquisas por `p.projeto_id`
(INT legado). `POST /pesquisas/` só popula `projeto_id_uuid`, então em todo projeto
criado pós-migração UUID o filtro casava zero linhas e o endpoint devolvia
HTTP 200 {"approved": 0} sem erro. As keywords ficavam presas em 'pending'.

O teste antigo (test_approve_classified.py) não pegou porque o fixture seedava
`projeto_id` INT explicitamente. Aqui os fixtures seedam pesquisas **só com UUID**
— exatamente o estado que a produção tinha.

Pré-condições:
- Túnel VPS Postgres aberto em localhost:5434.
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
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


async def _seed_uuid_only(conn, kws, status="classificado"):
    """Cria pesquisa vinculada APENAS por projeto_id_uuid (projeto_id INT = NULL).

    Esse é o estado real de produção que o bug original não enxergava.
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
        ids[kw] = await conn.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, $3, 'pending') RETURNING id""",
            pid, f"{kw}-{suffix}", kw_type,
        )
    return pid, ids


async def _cleanup(conn, pesquisa_id):
    await conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id)
    await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


async def _status_of(conn, kw_id):
    return await conn.fetchval("SELECT status FROM kw_staging WHERE id = $1", kw_id)


@pytest.mark.asyncio
async def test_regressao_pesquisa_sem_projeto_id_int(db_conn):
    """REGRESSÃO do bug: pesquisa só com UUID deve ser alcançada pelo approve.

    Antes do fix este teste falharia com approved=0.
    """
    pid, ids = await _seed_uuid_only(db_conn, [("kw-reg-a", "SECAO"), ("kw-reg-b", "PAGINA_GEO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r.status_code == 200, r.text
        assert await _status_of(db_conn, ids["kw-reg-a"]) == "approved"
        assert await _status_of(db_conn, ids["kw-reg-b"]) == "approved"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_approve_classified_tambem_alcanca_uuid_only(db_conn):
    """O endpoint legado herdou o mesmo fix — scripts antigos voltam a funcionar."""
    pid, ids = await _seed_uuid_only(db_conn, [("kw-legacy", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
        assert r.status_code == 200, r.text
        assert r.json()["approved"] >= 1
        assert await _status_of(db_conn, ids["kw-legacy"]) == "approved"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_approve_ids_seleciona_apenas_marcadas(db_conn):
    """Seleção explícita: só o id enviado sobe para approved."""
    pid, ids = await _seed_uuid_only(
        db_conn, [("kw-sel-1", "SECAO"), ("kw-sel-2", "SECAO")]
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"approve_ids": [ids["kw-sel-1"]]},
            )
        assert r.status_code == 200, r.text
        assert r.json()["approved"] == 1
        assert await _status_of(db_conn, ids["kw-sel-1"]) == "approved"
        assert await _status_of(db_conn, ids["kw-sel-2"]) == "pending"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_reclassify_antes_de_aprovar(db_conn):
    """DESCARTA reclassificada para SECAO no mesmo request deve ser aprovada."""
    pid, ids = await _seed_uuid_only(db_conn, [("kw-recl", "DESCARTA")])
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
        row = await db_conn.fetchrow(
            "SELECT kw_type, status FROM kw_staging WHERE id = $1", kid
        )
        assert row["kw_type"] == "SECAO"
        assert row["status"] == "approved"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_descarta_nao_e_aprovada_por_engano(db_conn):
    """approve_ids contendo DESCARTA → conta em skipped_descarta, continua pending."""
    pid, ids = await _seed_uuid_only(db_conn, [("kw-desc", "DESCARTA"), ("kw-ok", "SECAO")])
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
        assert await _status_of(db_conn, ids["kw-desc"]) == "pending"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_reject_marca_rejected(db_conn):
    pid, ids = await _seed_uuid_only(db_conn, [("kw-rej", "SECAO")])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/projetos/{PROJETO_MM_UUID}/keywords/approve",
                json={"reject_ids": [ids["kw-rej"]]},
            )
        assert r.status_code == 200, r.text
        assert r.json()["rejected"] == 1
        assert await _status_of(db_conn, ids["kw-rej"]) == "rejected"
    finally:
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_id_de_outro_projeto_vai_para_not_found(db_conn):
    """ID que não pertence ao projeto não quebra o lote — volta em not_found."""
    pid, ids = await _seed_uuid_only(db_conn, [("kw-own", "SECAO")])
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_kw_type_invalido_vai_para_invalid(db_conn):
    pid, ids = await _seed_uuid_only(db_conn, [("kw-inv", "SECAO")])
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_pesquisa_sobe_para_aprovado(db_conn):
    """Aprovar keywords de uma pesquisa 'classificado' promove a pesquisa."""
    pid, _ = await _seed_uuid_only(db_conn, [("kw-prom", "SECAO")], status="classificado")
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
        await _cleanup(db_conn, pid)


@pytest.mark.asyncio
async def test_idempotente(db_conn):
    """Rerun não reaprova nada e zera o saldo de pendentes desta pesquisa."""
    pid, _ = await _seed_uuid_only(db_conn, [("kw-idem", "SECAO")])
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
        await _cleanup(db_conn, pid)


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
async def test_listagem_traz_resumo_e_filtro_negado(db_conn):
    """GET com kw_type='!DESCARTA' e status='pending' alimenta o Passo 0 do seo-architect."""
    pid, _ = await _seed_uuid_only(
        db_conn, [("kw-list-1", "SECAO"), ("kw-list-2", "DESCARTA")]
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
        await _cleanup(db_conn, pid)
