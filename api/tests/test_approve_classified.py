"""REQ-8-03 — POST /projetos/{uuid}/keywords/approve-classified.

Estratégia: cada teste cria pesquisa (Postgres) + kws (Supabase), chama a API,
valida efeito no banco, cleanup no teardown.

## Fase 35 / D-02 — o seed atravessa os dois bancos
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

`pesquisas` fica no Postgres da Stack (`db_conn`); `kw_staging` mora no schema `leadgen`
do Supabase (`lg_conn`). Semear a keyword no banco errado passa silenciosamente.

Pré-condições:
- Túnel VPS aberto (`bash Full_AIOS_STACK/vps_tunnel.sh -d`) — Postgres em localhost:5433.
- `LEADGEN_DB_URL` resolvido pelo conftest.py (Supavisor session pooler).
- Migration 027 aplicada (UNIQUE natural pesquisas + competitor_audits).
- AUTH_ENABLED=false (setado no conftest.py).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_approve_classified.py -v
"""

import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

# Garante que api/ está no path para importar main.py como top-level
_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from main import app  # noqa: E402
import db as db_module  # noqa: E402


# UUID real do projeto MM Entulho no VPS (id_int_legado=8).
PROJETO_MM_UUID = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"
PROJETO_MM_INT = 8


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Fecha o pool asyncpg antes/depois de cada teste (mesma razão do test_pesquisas_conflict)."""
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
    """Supabase, schema `leadgen` — camada pré-decisão (`kw_staging`)."""
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"}
    )
    yield conn
    await conn.close()


async def _seed_pesquisa_with_pending_kws(conn, lg, projeto_uuid, projeto_id_int, kws):
    """Cria pesquisa status='aprovado' (Postgres) + kw_staging pending (Supabase)."""
    suffix = uuid.uuid4().hex[:8]
    pid = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel, projeto_id, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'aprovado', 'servico', $3, $4::uuid) RETURNING id""",
        "MM Entulho", f"nicho-approve-{suffix}", projeto_id_int, projeto_uuid,
    )
    for kw, kw_type in kws:
        await lg.execute(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, $3, 'pending')""",
            str(pid), f"{kw}-{suffix}", kw_type,
        )
    return pid


async def _cleanup_pesquisa(conn, lg, pesquisa_id):
    """Fase 35: o CASCADE de `pesquisas` → `kw_staging` não atravessa a fronteira dos
    bancos. O DELETE explícito no Supabase deixou de ser "clareza" e virou obrigação."""
    await lg.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", str(pesquisa_id))
    await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)


@pytest.mark.asyncio
async def test_approve_classified_happy(db_conn, lg_conn):
    """T1: pesquisa 'aprovado' com 3 pending (1 DESCARTA) → approved=2, skipped=1."""
    pid = await _seed_pesquisa_with_pending_kws(
        db_conn, lg_conn, PROJETO_MM_UUID, PROJETO_MM_INT,
        [("kw-happy-1", "PAGINA_PRINCIPAL"), ("kw-happy-2", "SECAO"), ("kw-happy-3", "DESCARTA")],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] >= 2, body  # pelo menos as 2 desta pesquisa
        assert body["skipped_descarta"] >= 1, body
        assert str(pid) in body["pesquisas_atualizadas"], body
    finally:
        await _cleanup_pesquisa(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_approve_classified_idempotent(db_conn, lg_conn):
    """T2 (CRIT-4): rerun imediato → approved=0."""
    pid = await _seed_pesquisa_with_pending_kws(
        db_conn, lg_conn, PROJETO_MM_UUID, PROJETO_MM_INT,
        [("kw-idem-1", "PAGINA_PRINCIPAL")],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
            assert r1.status_code == 200, r1.text
            assert r1.json()["approved"] >= 1
            r2 = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
            assert r2.status_code == 200, r2.text
            assert r2.json()["approved"] == 0
    finally:
        await _cleanup_pesquisa(db_conn, lg_conn, pid)


@pytest.mark.asyncio
async def test_approve_classified_projeto_404():
    """T3: UUID inexistente → 404 pt-BR."""
    fake_uuid = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{fake_uuid}/keywords/approve-classified")
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


@pytest.mark.asyncio
async def test_approve_classified_response_shape():
    """T4 (renomeado do plan-checker warning): valida shape do response mesmo sem pending real."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("approved"), int)
    assert isinstance(body.get("skipped_descarta"), int)
    assert isinstance(body.get("pesquisas_atualizadas"), list)


@pytest.mark.asyncio
async def test_approve_classified_uuid_invalido():
    """T5: UUID malformado → 422 do helper OU 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/projetos/not-a-uuid/keywords/approve-classified")
    assert r.status_code in (404, 422), r.text


@pytest.mark.asyncio
async def test_approve_classified_skipped_descarta_conta_correto(db_conn, lg_conn):
    """T6: 3 DESCARTA pending + 5 SECAO pending → approved=5, skipped>=3.

    Uso >= porque pode haver outras pesquisas pending no projeto — isolamos
    contando efeito no fixture próprio via query direta ao banco.
    """
    pid = await _seed_pesquisa_with_pending_kws(
        db_conn, lg_conn, PROJETO_MM_UUID, PROJETO_MM_INT,
        [
            ("kw-desc-1", "DESCARTA"), ("kw-desc-2", "DESCARTA"), ("kw-desc-3", "DESCARTA"),
            ("kw-sec-1", "SECAO"), ("kw-sec-2", "SECAO"), ("kw-sec-3", "SECAO"),
            ("kw-sec-4", "SECAO"), ("kw-sec-5", "SECAO"),
        ],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{PROJETO_MM_UUID}/keywords/approve-classified")
        assert r.status_code == 200, r.text

        # Valida efeito local: dos 8 seeds, 5 SECAO devem estar 'approved', 3 DESCARTA continuam 'pending'
        approved_local = await lg_conn.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid AND status = 'approved'",
            str(pid),
        )
        pending_descarta_local = await lg_conn.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid AND status = 'pending' AND UPPER(kw_type) = 'DESCARTA'",
            str(pid),
        )
        assert approved_local == 5, f"esperado 5 approved locais, tem {approved_local}"
        assert pending_descarta_local == 3, f"DESCARTA deveria continuar pending, tem {pending_descarta_local}"
    finally:
        await _cleanup_pesquisa(db_conn, lg_conn, pid)
