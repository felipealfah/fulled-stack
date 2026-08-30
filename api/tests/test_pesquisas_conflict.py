"""Testes REQ-8-08: POST /pesquisas/ retorna 409 com pesquisa_id existente após retry.

Fase 35 / D-06 — este arquivo passou a atravessar DOIS bancos:
  `pesquisas`/`projetos`/`agent_executions` → Postgres da Stack (`DATABASE_URL`)
  `kw_staging`                              → Supabase, schema leadgen (`LEADGEN_DB_URL`)

Pré-condições:
- Túnel VPS Postgres aberto em localhost:5433 (`bash Full_AIOS_STACK/vps_tunnel.sh -d`).
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
import routers.review as review_module  # noqa: E402


async def _conn_pg():
    """Conexão avulsa com o Postgres da Stack (camada de decisão)."""
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"])


async def _conn_leadgen():
    """Conexão avulsa com o Supabase, schema `leadgen` (camada pré-decisão).

    `search_path` replica o `server_settings` de `db_leadgen.get_lg_pool` — sem ele
    `FROM kw_staging` não resolve e o teste falha com UndefinedTableError.
    """
    import asyncpg
    return await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"}
    )


async def _kw_count(pesquisa_id: str) -> int:
    """Conta as keywords daquela pesquisa no Supabase."""
    c = await _conn_leadgen()
    try:
        return await c.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id
        )
    finally:
        await c.close()


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
    """Remove pesquisa criada pelos testes para manter idempotência entre runs.

    Fase 35 / D-06: `kw_staging` NÃO cascateia mais — a FK que a apagava junto com a
    pesquisa não existe desde que a tabela mudou de banco. Sem o DELETE explícito no
    Supabase, cada rodada da suíte deixaria keywords órfãs para trás (SC-04).
    Filhos primeiro, pesquisa por último — a mesma ordem do `DELETE /pesquisas/{id}`.
    """
    conn = await _conn_pg()
    try:
        ids = [
            r["id"]
            for r in await conn.fetch("SELECT id FROM pesquisas WHERE nicho = $1", nicho)
        ]
    finally:
        await conn.close()

    if ids:
        c_lg = await _conn_leadgen()
        try:
            await c_lg.execute(
                "DELETE FROM kw_staging WHERE pesquisa_id = ANY($1::uuid[])", ids
            )
        finally:
            await c_lg.close()

    conn = await _conn_pg()
    try:
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
            pesquisa_id = r1.json()["pesquisa"]["id"]
            r2 = await c.post("/pesquisas/", json=payload)
            assert r2.status_code == 409

        # Fase 35: o JOIN cross-fronteira virou duas leituras. A pesquisa é resolvida
        # no Postgres e a contagem é feita no Supabase — o mesmo que o JOIN media.
        conn = await _conn_pg()
        try:
            ids = await conn.fetch(
                """SELECT id FROM pesquisas
                    WHERE nicho = $1 AND projeto_id_uuid = $2::uuid""",
                payload["nicho"], PROJETO_UUID_MM_ENTULHO,
            )
        finally:
            await conn.close()
        assert len(ids) == 1, f"pesquisa duplicada: {len(ids)} rows (esperado 1)"

        count = await _kw_count(pesquisa_id)
        assert count == 1, f"kw_staging duplicado: {count} rows (esperado 1)"
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_keywords_gravadas_batem_com_as_enviadas(
    unique_pesquisa_payload_com_projeto,
):
    """Paridade: cada keyword não-DESCARTA enviada vira uma linha no Supabase.

    É o teste que pega a etapa 2 virar no-op silencioso — a resposta continuaria
    dizendo `keywords_inseridas: N` enquanto o Supabase ficaria vazio, e o pipeline
    a jusante encontraria uma pesquisa sem keyword nenhuma.
    """
    payload = dict(unique_pesquisa_payload_com_projeto)
    payload["keywords"] = [
        {"keyword": "kw paridade 1", "kw_type": "PAGINA_PRINCIPAL", "avg_monthly_searches": 320},
        {"keyword": "kw paridade 2", "kw_type": "SERVICO"},
        {"keyword": "kw paridade 3", "kw_type": "PAGINA_GEO"},
        {"keyword": "kw paridade descartada", "kw_type": "DESCARTA"},
    ]
    esperado = 3  # a DESCARTA é ignorada por skip_descarta=True (default)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/pesquisas/", json=payload)
            assert r.status_code == 200, r.text
            body = r.json()
            pesquisa_id = body["pesquisa"]["id"]

        assert body["keywords_inseridas"] == esperado
        assert body["keywords_ignoradas_descarta"] == 1

        gravadas = await _kw_count(pesquisa_id)
        assert gravadas == esperado, (
            f"a resposta diz {esperado} keywords, o Supabase tem {gravadas}"
        )

        # E os valores atravessaram como valores, não como texto de SQL (T-35-06).
        c_lg = await _conn_leadgen()
        try:
            rows = await c_lg.fetch(
                """SELECT keyword, kw_type, avg_monthly_searches, status
                     FROM kw_staging WHERE pesquisa_id = $1::uuid ORDER BY keyword""",
                pesquisa_id,
            )
        finally:
            await c_lg.close()
        assert [r["keyword"] for r in rows] == [
            "kw paridade 1", "kw paridade 2", "kw paridade 3"
        ]
        assert rows[0]["avg_monthly_searches"] == 320
        assert {r["status"] for r in rows} == {"pending"}
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_falha_do_supabase_deixa_pesquisa_sem_keywords_e_o_retry_cura(
    unique_pesquisa_payload_com_projeto, monkeypatch,
):
    """A ordem Postgres→Supabase, provada por injeção de falha ENTRE as duas escritas.

    Fase 35 / D-06. Se a ordem fosse a do `/approve` (Supabase primeiro), uma falha
    do Postgres deixaria keywords apontando para uma pesquisa inexistente — órfãs que
    nenhuma FK recusa mais. Na ordem certa a janela produz o estado oposto: a pesquisa
    existe **sem** keywords, o cliente é avisado em pt-BR, e reexecutar converge.
    """
    payload = unique_pesquisa_payload_com_projeto

    async def _pool_indisponivel():
        raise ConnectionError("supabase fora do ar (injetado pelo teste)")

    try:
        monkeypatch.setattr(review_module, "get_lg_pool", _pool_indisponivel)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/pesquisas/", json=payload)

        # Nunca um 500 mudo: a mensagem em pt-BR explica o efeito parcial.
        assert r.status_code == 500, r.text
        detalhe = r.json()["detail"]
        assert "pesquisa foi criada" in detalhe
        assert "Reexecute" in detalhe

        # Etapa 1 durável: a pesquisa está no Postgres...
        conn = await _conn_pg()
        try:
            row = await conn.fetchrow(
                "SELECT id, status FROM pesquisas WHERE nicho = $1", payload["nicho"]
            )
        finally:
            await conn.close()
        assert row is not None, "a pesquisa deveria ter sido gravada ANTES do Supabase"
        assert row["status"] == "classificado"

        # ...e nenhuma keyword órfã ficou do outro lado.
        assert await _kw_count(str(row["id"])) == 0

        # A cura: reexecutar cai no 409 já tratado, com o pesquisa_id existente.
        monkeypatch.undo()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r2 = await c.post("/pesquisas/", json=payload)
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["pesquisa_id"] == str(row["id"])
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_reject_limpa_supabase_e_marca_postgres(
    unique_pesquisa_payload_com_projeto,
):
    """POST /reject zera kw_staging no Supabase E marca 'rejected' no Postgres.

    Fase 35 / D-06: as duas pontas da escrita cross-DB, conferidas nos bancos e não
    só na resposta HTTP.
    """
    payload = unique_pesquisa_payload_com_projeto
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/pesquisas/", json=payload)
            assert r.status_code == 200, r.text
            pesquisa_id = r.json()["pesquisa"]["id"]
            assert await _kw_count(pesquisa_id) == 1

            rej = await c.post(f"/pesquisas/{pesquisa_id}/reject")
            assert rej.status_code == 200, rej.text
            # A chave `message` é contrato — o texto não muda com a migração.
            assert rej.json() == {
                "ok": True,
                "message": f"Pesquisa {pesquisa_id} rejeitada e removida do staging",
            }

        assert await _kw_count(pesquisa_id) == 0

        conn = await _conn_pg()
        try:
            status = await conn.fetchval(
                "SELECT status FROM pesquisas WHERE id = $1::uuid", pesquisa_id
            )
        finally:
            await conn.close()
        assert status == "rejected"
    finally:
        await _cleanup_pesquisa_por_nicho(payload["nicho"])


@pytest.mark.asyncio
async def test_reject_de_pesquisa_inexistente_404_sem_tocar_o_supabase():
    """O 404 sai do passo 1, antes de qualquer escrita nos dois bancos."""
    inexistente = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/pesquisas/{inexistente}/reject")
    assert r.status_code == 404
    assert r.json()["detail"] == "Pesquisa não encontrada"


@pytest.mark.asyncio
async def test_delete_keyword_de_outra_pesquisa_404_e_nao_apaga(
    unique_pesquisa_payload_com_projeto,
):
    """T-35-05: sem FK cross-DB, o `AND pesquisa_id` é o que impede a travessia.

    Passa um `keyword_id` real, mas de OUTRA pesquisa. Tem de dar 404 e a keyword
    alheia tem de continuar viva.
    """
    payload_a = unique_pesquisa_payload_com_projeto
    suffix = uuid.uuid4().hex[:8]
    payload_b = {
        **payload_a,
        "nicho": f"nicho-conflict-b-{suffix}",
        "keywords": [{"keyword": "kw da pesquisa B", "kw_type": "SERVICO"}],
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            ra = await c.post("/pesquisas/", json=payload_a)
            rb = await c.post("/pesquisas/", json=payload_b)
            assert ra.status_code == 200 and rb.status_code == 200, (ra.text, rb.text)
            id_a = ra.json()["pesquisa"]["id"]
            id_b = rb.json()["pesquisa"]["id"]

            c_lg = await _conn_leadgen()
            try:
                kw_b = await c_lg.fetchval(
                    "SELECT id FROM kw_staging WHERE pesquisa_id = $1::uuid", id_b
                )
            finally:
                await c_lg.close()

            # keyword de B, endereçada pela pesquisa A
            r = await c.delete(f"/pesquisas/{id_a}/keywords/{kw_b}")
            assert r.status_code == 404, r.text
            assert r.json()["detail"] == "Keyword não encontrada"

            assert await _kw_count(id_b) == 1, "a keyword de B não podia ter sido apagada"

            # e o caminho legítimo continua funcionando
            ok = await c.delete(f"/pesquisas/{id_b}/keywords/{kw_b}")
            assert ok.status_code == 200, ok.text
            assert await _kw_count(id_b) == 0
    finally:
        await _cleanup_pesquisa_por_nicho(payload_a["nicho"])
        await _cleanup_pesquisa_por_nicho(payload_b["nicho"])


@pytest.mark.asyncio
async def test_list_pesquisas_conta_keywords_do_supabase(
    unique_pesquisa_payload_com_projeto,
):
    """GET /pesquisas/ casa Postgres × Supabase e devolve 0 para pesquisa sem keyword.

    Fase 35 / D-02: o COUNT/GROUP BY saiu do SQL. O caso que o `LEFT JOIN` cobria de
    graça — pesquisa **sem nenhuma keyword** — é o que o casamento em memória erra com
    mais facilidade, devolvendo `None` (ou nem a chave) em vez do `0` de antes.
    """
    com_kw = unique_pesquisa_payload_com_projeto
    suffix = uuid.uuid4().hex[:8]
    sem_kw = {
        **com_kw,
        "nicho": f"nicho-conflict-vazia-{suffix}",
        "keywords": [],
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post("/pesquisas/", json=com_kw)
            r2 = await c.post("/pesquisas/", json=sem_kw)
            assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
            id_com, id_sem = r1.json()["pesquisa"]["id"], r2.json()["pesquisa"]["id"]

            lst = await c.get("/pesquisas/")
            assert lst.status_code == 200, lst.text
            linhas = {row["id"]: row for row in lst.json()}

        assert linhas[id_com]["total_keywords"] == 1
        # o LEFT JOIN + COUNT devolvia 0, nunca None — o casamento tem de fazer o mesmo
        assert linhas[id_sem]["total_keywords"] == 0
        assert linhas[id_sem]["total_keywords"] is not None

        # `total_keywords` continua sendo a ÚLTIMA chave da linha (contrato de ordem)
        assert list(linhas[id_com])[-1] == "total_keywords"

        # ordem preservada: created_at DESC
        ordem = [row["created_at"] for row in lst.json()]
        assert ordem == sorted(ordem, reverse=True)
    finally:
        await _cleanup_pesquisa_por_nicho(com_kw["nicho"])
        await _cleanup_pesquisa_por_nicho(sem_kw["nicho"])
