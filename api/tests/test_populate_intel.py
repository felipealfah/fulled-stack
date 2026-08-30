"""Plan 32-03 — POST /projetos/{id}/seo-plan/populate-intel (KWMGMT-04).

Testes cobrem:
- Happy path: 1 page com kw_principal_id → pages_updated=1, difficulty mapeado
- Fallback max competitive_score quando kw_principal_id é NULL
- Sem intel disponível → pages_sem_intel contém o page_id
- Idempotência: dois POSTs → pages_updated=1 nas duas chamadas
- Projeto não encontrado → 404
- Lote misto (atualizáveis e puláveis intercaladas) → cada página com o SEU score
- Lote de 30 páginas → tempo de parede abaixo do limite acordado

Pré-condições:
- Túnel do Postgres da Stack aberto (`bash Full_AIOS_STACK/vps_tunnel.sh -d`, localhost:5433).
- Migration 030 bloco B aplicado (CHECK difficulty tolerante).
- As duas DSNs resolvidas pelo `conftest.py` (DATABASE_URL e LEADGEN_DB_URL); AUTH_ENABLED=false.

⚠️ Este módulo NÃO define `os.environ["DATABASE_URL"]`. Até a Fase 35 ele fazia isso em
nível de módulo, com a senha de produção versionada e uma DSN morta (`localhost:5432`,
stack local desligado). Como o pytest importa TODOS os módulos de teste na coleção, essa
única linha envenenava a sessão inteira — `pytest api/tests -q` dava
`53 failed, 7 passed, 59 errors` com a linha e `111 passed, 3 failed` sem ela.
Não reintroduzir: as DSNs vêm do `conftest.py`, como em todos os outros arquivos.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_populate_intel.py -v
"""

import os
import sys
import time
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
    """Postgres da Stack — camada de decisão: `projetos`, `pesquisas`."""
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    yield conn
    await conn.close()


@pytest.fixture
async def lg_conn():
    """Supabase, schema `leadgen` (Fase 35 / D-02).

    `kw_staging`, `projeto_seo_plan` e `projeto_seo_plan_pages` — as três tabelas do laço
    de `populate_intel` — migraram juntas. O seed tem de acompanhá-las: uma linha semeada
    no Postgres seria invisível para o endpoint, e o teste falharia por motivo errado.
    """
    dsn = os.environ["LEADGEN_DB_URL"]
    conn = await asyncpg.connect(dsn, server_settings={"search_path": "leadgen"})
    yield conn
    await conn.close()


# ---------------------------------------------------------------------------
# Helpers de seed — cada um contra o banco onde a tabela realmente mora
# ---------------------------------------------------------------------------

async def _seed_projeto(conn) -> tuple[str, int]:
    """Cria projeto e retorna (uuid_str, id_int_legado)."""
    suffix = uuid.uuid4().hex[:8]
    row = await conn.fetchrow(
        """INSERT INTO projetos (projeto_nome, nicho, cidade, status)
           VALUES ($1, $2, 'Brasília', 'research') RETURNING id, id_int_legado""",
        f"Test-PopIntel-{suffix}",
        f"nicho-popintel-{suffix}",
    )
    return str(row["id"]), row["id_int_legado"]


async def _seed_pesquisa(conn, projeto_id_uuid: str) -> str:
    """Cria pesquisa vinculada ao projeto. Retorna pesquisa_id (uuid str).

    Status `aprovado`: o `pesquisas_status_check` do Postgres de produção aceita
    apenas {pending_review, approved, rejected, classificado, aprovado}. O valor
    anterior (`gate_2_approved`) só existia no banco de dev que a DSN morta do
    topo deste arquivo apontava. `populate_intel` não filtra por status da
    pesquisa, então a escolha não afeta o comportamento sob teste.
    """
    suffix = uuid.uuid4().hex[:8]
    pid = await conn.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', 'aprovado', $3::uuid) RETURNING id""",
        f"Test-PopIntel-Pesq-{suffix}",
        f"nicho-pesq-pi-{suffix}",
        projeto_id_uuid,
    )
    return str(pid)


async def _seed_kw(conn, pesquisa_id: str, competitive_score: float | None = None,
                   difficulty_label: str | None = None) -> int:
    """Cria kw_staging. Retorna kw_id (int)."""
    suffix = uuid.uuid4().hex[:6]
    kwid = await conn.fetchval(
        """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status,
                                   competitive_score, difficulty_label, top_competitor_url)
           VALUES ($1::uuid, $2, 'PAGINA_PRINCIPAL', 'approved', $3, $4, $5) RETURNING id""",
        pesquisa_id,
        f"kw-pi-{suffix}",
        competitive_score,
        difficulty_label,
        "https://exemplo.com" if competitive_score is not None else None,
    )
    return kwid


async def _seed_seo_plan(conn, pid_int: int) -> int:
    """Cria projeto_seo_plan. Retorna plan_id (int)."""
    plan_id = await conn.fetchval(
        """INSERT INTO projeto_seo_plan (projeto_id, status)
           VALUES ($1, 'rascunho') RETURNING id""",
        pid_int,
    )
    return plan_id


async def _seed_page(conn, plan_id: int, pesquisa_id: str,
                     kw_principal_id: int | None = None) -> int:
    """Cria projeto_seo_plan_pages. Retorna page_id (int)."""
    page_id = await conn.fetchval(
        """INSERT INTO projeto_seo_plan_pages (plan_id, pesquisa_id, kw_principal_id, papel)
           VALUES ($1, $2::uuid, $3, 'principal') RETURNING id""",
        plan_id,
        pesquisa_id,
        kw_principal_id,
    )
    return page_id


async def _cleanup(db_conn, lg_conn, projeto_uuid: str, pid_int: int, pesquisa_ids: list[str]):
    """Cleanup em ordem reversa das FKs, agora em DOIS bancos (Fase 35 / D-02).

    `pesquisa_ids` chega explícito em vez de ser redescoberto por
    `SELECT id FROM pesquisas WHERE projeto_id_uuid = ...`: essa consulta cruzaria a
    fronteira (pesquisas no Postgres, kw_staging no Supabase) e, pior, devolveria vazio
    sempre que o teste falhasse depois de a pesquisa já ter sido apagada — deixando
    órfãos no Supabase. Lição do Plan 35-05, desvio 4.
    """
    # Supabase — projeto_seo_plan_pages sai em cascade com o plano
    await lg_conn.execute("DELETE FROM projeto_seo_plan WHERE projeto_id = $1", pid_int)
    if pesquisa_ids:
        await lg_conn.execute(
            "DELETE FROM kw_staging WHERE pesquisa_id = ANY($1::uuid[])", pesquisa_ids
        )
    # Postgres
    await db_conn.execute("DELETE FROM pesquisas WHERE projeto_id_uuid = $1::uuid", projeto_uuid)
    await db_conn.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_uuid)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_populate_intel_happy(db_conn, lg_conn):
    """T1: 1 page, kw com score=42, label='LOW' → pages_updated=1, difficulty='baixo'."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_id = await _seed_kw(lg_conn, pesq_id, competitive_score=42.0, difficulty_label="LOW")
        plan_id = await _seed_seo_plan(lg_conn, pid_int)
        page_id = await _seed_page(lg_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 1
        assert body["pages_sem_intel"] == []

        row = await lg_conn.fetchrow(
            "SELECT competitive_score, difficulty_label FROM projeto_seo_plan_pages WHERE id = $1",
            page_id,
        )
        assert row["competitive_score"] == 42
        assert row["difficulty_label"] == "baixo"
    finally:
        await _cleanup(db_conn, lg_conn, proj_uuid, pid_int, [pesq_id])


@pytest.mark.asyncio
async def test_populate_intel_fallback_max_score(db_conn, lg_conn):
    """T2: page sem kw_principal_id, 3 kws com scores 30/50/20 → recebe kw score=50."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_ids = []
        for score in [30.0, 50.0, 20.0]:
            kw_id = await _seed_kw(lg_conn, pesq_id, competitive_score=score, difficulty_label="MED")
            kw_ids.append(kw_id)

        plan_id = await _seed_seo_plan(lg_conn, pid_int)
        page_id = await _seed_page(lg_conn, plan_id, pesq_id, kw_principal_id=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 1
        assert body["pages_sem_intel"] == []

        row = await lg_conn.fetchrow(
            "SELECT competitive_score FROM projeto_seo_plan_pages WHERE id = $1",
            page_id,
        )
        assert row["competitive_score"] == 50, f"Esperava score 50 (max), recebi {row['competitive_score']}"
    finally:
        await _cleanup(db_conn, lg_conn, proj_uuid, pid_int, [pesq_id])


@pytest.mark.asyncio
async def test_populate_intel_pages_sem_intel(db_conn, lg_conn):
    """T3: page com kw que tem competitive_score=NULL → pages_updated=0, pages_sem_intel=[page_id]."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_id = await _seed_kw(lg_conn, pesq_id, competitive_score=None, difficulty_label=None)
        plan_id = await _seed_seo_plan(lg_conn, pid_int)
        page_id = await _seed_page(lg_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 0
        assert page_id in body["pages_sem_intel"]
    finally:
        await _cleanup(db_conn, lg_conn, proj_uuid, pid_int, [pesq_id])


@pytest.mark.asyncio
async def test_populate_intel_idempotent(db_conn, lg_conn):
    """T4: POST 2× → pages_updated=1 nas duas chamadas."""
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    try:
        pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
        kw_id = await _seed_kw(lg_conn, pesq_id, competitive_score=60.0, difficulty_label="HIGH")
        plan_id = await _seed_seo_plan(lg_conn, pid_int)
        await _seed_page(lg_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
            r2 = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")

        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r1.json()["pages_updated"] == 1
        assert r2.json()["pages_updated"] == 1
    finally:
        await _cleanup(db_conn, lg_conn, proj_uuid, pid_int, [pesq_id])


@pytest.mark.asyncio
async def test_populate_intel_projeto_not_found():
    """T5: POST em UUID inexistente → 404."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{fake}/seo-plan/populate-intel")
    assert r.status_code == 404, r.text
    assert "Projeto" in r.json()["detail"]


@pytest.mark.asyncio
async def test_populate_intel_lote_misto_nao_desalinha(db_conn, lg_conn):
    """T6: lote com páginas atualizáveis E puláveis intercaladas.

    Regressão específica da reescrita em lote da Fase 35: o laço antigo fazia um UPDATE
    por página, então pular uma era inofensivo. Agora as páginas atualizáveis vão em
    ARRAYS PARALELOS e as puladas ficam de fora — se o casamento desalinhar, uma página
    recebe o score de outra e o teste continuaria verde olhando só para `pages_updated`.
    Por isso a asserção é sobre QUAL página recebeu QUAL score, no banco.

    Ordem semeada: [com score 42] → [kw sem score] → [com score 77] → [sem kw e sem
    keyword pontuada]. Só a 1ª e a 3ª podem ser atualizadas.
    """
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    pesquisa_ids: list[str] = []
    try:
        plan_id = await _seed_seo_plan(lg_conn, pid_int)

        async def _pagina(score, label, com_kw=True):
            pesq = await _seed_pesquisa(db_conn, proj_uuid)
            pesquisa_ids.append(pesq)
            kw_id = None
            if com_kw:
                kw_id = await _seed_kw(lg_conn, pesq, competitive_score=score,
                                       difficulty_label=label)
            return await _seed_page(lg_conn, plan_id, pesq, kw_principal_id=kw_id)

        page_ok_1 = await _pagina(42.0, "LOW")
        page_kw_sem_score = await _pagina(None, None)
        page_ok_2 = await _pagina(77.0, "HIGH")
        page_sem_kw = await _pagina(None, None, com_kw=False)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == 2, body
        assert set(body["pages_sem_intel"]) == {page_kw_sem_score, page_sem_kw}, body

        rows = await lg_conn.fetch(
            """SELECT id, competitive_score, difficulty_label
               FROM projeto_seo_plan_pages WHERE id = ANY($1::int[])""",
            [page_ok_1, page_kw_sem_score, page_ok_2, page_sem_kw],
        )
        por_id = {r["id"]: r for r in rows}
        # Cada página com o SEU score — desalinhamento trocaria 42 por 77
        assert por_id[page_ok_1]["competitive_score"] == 42
        assert por_id[page_ok_1]["difficulty_label"] == "baixo"
        assert por_id[page_ok_2]["competitive_score"] == 77
        assert por_id[page_ok_2]["difficulty_label"] == "alto"
        # As puladas não foram tocadas
        assert por_id[page_kw_sem_score]["competitive_score"] is None
        assert por_id[page_sem_kw]["competitive_score"] is None
    finally:
        await _cleanup(db_conn, lg_conn, proj_uuid, pid_int, pesquisa_ids)


LIMITE_SEGUNDOS_LOTE = 5.0
N_PAGINAS_LOTE = 30


@pytest.mark.asyncio
async def test_populate_intel_lote_grande_dentro_do_limite(db_conn, lg_conn):
    """T7 (Fase 35 / D-02): 30 páginas → tempo de parede < 5 s.

    O laço de `populate_intel` faz até dois round-trips por página. Enquanto as tabelas
    moravam no Postgres local isso era irrelevante; contra o Supabase cada round-trip
    atravessa a internet. Este teste é o instrumento de MEDIDA que autoriza (ou não) a
    reescrita em lote: enquanto ele passar, converter o laço em
    `SELECT` + `UPDATE ... FROM unnest(...)` seria otimizar sem medir.

    Ele também é a regressão de T-35-10: se alguém reintroduzir um `acquire()` por
    iteração, o custo do handshake vira linear e o limite estoura.
    """
    proj_uuid, pid_int = await _seed_projeto(db_conn)
    pesquisa_ids: list[str] = []
    try:
        plan_id = await _seed_seo_plan(lg_conn, pid_int)

        # Uma pesquisa por página: `projeto_seo_plan_pages` tem UNIQUE
        # (plan_id, pesquisa_id), então 30 páginas do mesmo plano exigem 30 pesquisas
        # distintas — que é também a forma real do dado. Cada página recebe
        # `kw_principal_id`, o ramo caro do laço (um fetchrow + um execute por página).
        for _ in range(N_PAGINAS_LOTE):
            pesq_id = await _seed_pesquisa(db_conn, proj_uuid)
            pesquisa_ids.append(pesq_id)
            kw_id = await _seed_kw(
                lg_conn, pesq_id, competitive_score=55.0, difficulty_label="MED"
            )
            await _seed_page(lg_conn, plan_id, pesq_id, kw_principal_id=kw_id)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Uma chamada de aquecimento: o custo do primeiro `acquire()` inclui o
            # handshake TLS do pool e não é o que este teste mede.
            await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")

            inicio = time.perf_counter()
            r = await c.post(f"/projetos/{proj_uuid}/seo-plan/populate-intel")
            decorrido = time.perf_counter() - inicio

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pages_updated"] == N_PAGINAS_LOTE, body
        assert body["pages_sem_intel"] == []
        assert decorrido < LIMITE_SEGUNDOS_LOTE, (
            f"{N_PAGINAS_LOTE} páginas levaram {decorrido:.2f}s "
            f"(limite {LIMITE_SEGUNDOS_LOTE}s) — o laço item a item deixou de caber; "
            "converter em duas instruções de lote com unnest, como intel.py e kw_mgmt.py"
        )
        print(f"[populate-intel] {N_PAGINAS_LOTE} páginas em {decorrido:.2f}s")
    finally:
        await _cleanup(db_conn, lg_conn, proj_uuid, pid_int, pesquisa_ids)
