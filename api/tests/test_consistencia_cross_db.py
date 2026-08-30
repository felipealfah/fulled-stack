"""SC-03 — falha parcial e convergência nos TRÊS fluxos que escrevem nos dois bancos.

ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

A Fase 35 partiu transações que eram únicas em pares de escritas em bancos diferentes.
Não existe transação atravessando a fronteira, e a fase decidiu (D-06) **não** adotar
outbox nem saga: em vez disso, cada fluxo escolhe a ORDEM que torna a janela de falha
conservadora, e a cura é reexecutar a mesma chamada.

A ordem não é um padrão único da fase — ela segue a **direção da referência**:

| Fluxo | Ordem | Por quê |
|---|---|---|
| `POST /projetos/{id}/keywords/approve` | Supabase → Postgres | a keyword aprovada é o *fato*; `pesquisas.status` é a *projeção* |
| `POST /pesquisas/` | Postgres → Supabase | `kw_staging.pesquisa_id` *referencia* a pesquisa |
| `POST /pesquisas/{id}/approve-gate2` | Supabase → Postgres | mesmo motivo do `/approve` (fato antes da projeção) |

Copiar a ordem de um fluxo para o outro produz exatamente o bug que ela evita. Este
arquivo é o que faz essa afirmação parar de ser prosa da RESEARCH.md: cada fluxo é
exercido com **injeção de falha real** no passo que a ordem protege, e o estado é
conferido **nos dois bancos por asyncpg** — nunca pela API, que é o que está sob teste.

Lição do Plan 35-08, aplicada aqui: injetar a falha do lado errado produz um teste que
passa sob a mutação que inverte a ordem. Por isso o fluxo 3 tem DOIS casos — com o
Supabase fora (o caso que **discrimina** a ordem) e com o Postgres fora (o caso do
`aviso` e da convergência).

Isolamento (T-35-12): cada teste cria o **próprio projeto** com nome único, e todo id é
gerado na hora. Nenhum UUID de produção é usado — este arquivo escreve e falha de
propósito, e um `/approve` com `approve_all_non_descarta` alcança todas as pesquisas do
projeto que receber. O teardown roda em `finally` e limpa os dois bancos, filhos primeiro.

Pré-condições:
- Túnel VPS aberto (`bash Full_AIOS_STACK/vps_tunnel.sh -d`) — Postgres em localhost:5433.
- `LEADGEN_DB_URL` resolvida pelo conftest.py (Supavisor session pooler).
- AUTH_ENABLED=false (setado no conftest.py).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_consistencia_cross_db.py -v
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
import routers.keywords as kw_module  # noqa: E402
import routers.review as review_module  # noqa: E402

# Contrato do `/approve` congelado no Plan 35-07 (SC-01): `aviso` é a 9ª chave e só
# aparece no caminho degradado.
CHAVES_APPROVE = {
    "approved", "rejected", "reclassified", "skipped_descarta",
    "pending_restantes", "pesquisas_atualizadas", "not_found", "invalid",
}


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Espelha o reset de `db._pool` dos outros arquivos.

    O reset de `db_leadgen._lg_pool` já vem do conftest.py (fixture autouse) — não
    duplicar aqui. Sem os dois, um pool criado no event loop do teste anterior
    sobrevive e o seguinte morre com 'Event loop is closed'.
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
async def pg():
    """Postgres da Stack — camada de decisão (`projetos`, `pesquisas`)."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    yield conn
    await conn.close()


@pytest.fixture
async def lg():
    """Supabase, schema `leadgen` — camada pré-decisão (`kw_staging`).

    `search_path` replica o `server_settings` de `db_leadgen.get_lg_pool`; sem ele
    `FROM kw_staging` não resolve.
    """
    conn = await asyncpg.connect(
        os.environ["LEADGEN_DB_URL"], server_settings={"search_path": "leadgen"}
    )
    yield conn
    await conn.close()


@pytest.fixture
def sem_bq(monkeypatch):
    """Desliga o espelho no BigQuery nos testes do gate.

    O bloco é best-effort desde o Plan 35-08 e não afeta o que se mede aqui, mas
    deixá-lo ligado escreveria linhas de teste em `leadgen_silver.kw_plan` — efeito
    fora dos dois bancos que o teardown alcança.
    """
    monkeypatch.setattr(review_module, "_get_bq_client", lambda: None)


# ── Injeção de falha ────────────────────────────────────────────────────────


class _PoolQueCaiApos:
    """Proxy do POOL — não do `acquire`, que é read-only em C no asyncpg.

    `apos=1` deixa a primeira aquisição passar (a leitura/resolução, que roda no
    Postgres antes de qualquer escrita) e estoura da segunda em diante: exatamente a
    janela entre o commit no Supabase e a escrita no Postgres.

    Atenção (lição do Plan 35-08): em `approve_gate2` o objeto pool é capturado uma
    vez e reusado, então trocar `get_pool` por uma função que falha NÃO atinge os
    passos que reusam o objeto. Só o proxy do pool alcança as duas aquisições.
    """

    def __init__(self, real, apos: int = 1):
        self._real = real
        self._apos = apos
        self.n = 0

    def __getattr__(self, nome):
        return getattr(self._real, nome)

    def acquire(self, *a, **kw):
        self.n += 1
        if self.n > self._apos:
            raise ConnectionError("postgres indisponível (injetado pelo teste)")
        return self._real.acquire(*a, **kw)


async def _pool_indisponivel():
    """Substitui `get_lg_pool`: o Supabase nem chega a ser contatado."""
    raise ConnectionError("supabase indisponível (injetado pelo teste)")


def _quebrar_postgres(monkeypatch, modulo, pool_real, apos: int = 1) -> _PoolQueCaiApos:
    proxy = _PoolQueCaiApos(pool_real, apos)

    async def _get_pool_quebrado():
        return proxy

    monkeypatch.setattr(modulo, "get_pool", _get_pool_quebrado)
    return proxy


# ── Semeadura isolada ───────────────────────────────────────────────────────


async def _seed_projeto(pg) -> tuple[str, int]:
    """Projeto exclusivo do teste. `id_int_legado` vem da sequence."""
    suf = uuid.uuid4().hex[:8]
    row = await pg.fetchrow(
        """INSERT INTO projetos (projeto_nome, nicho, cidade, status)
           VALUES ($1, $2, 'Brasília', 'research')
           RETURNING id, id_int_legado""",
        f"Test-Consist-{suf}", f"nicho-consist-{suf}",
    )
    return str(row["id"]), row["id_int_legado"]


async def _seed_pesquisa(pg, lg, projeto_uuid: str, kws, status: str = "classificado"):
    """Pesquisa no Postgres, keywords no Supabase. Semear no banco errado passa mudo."""
    suf = uuid.uuid4().hex[:8]
    pid = await pg.fetchval(
        """INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel,
                                  projeto_id, projeto_id_uuid)
           VALUES ($1, $2, 'Brasília', $3, 'servico', NULL, $4::uuid)
           RETURNING id""",
        f"Test-Consist-{suf}", f"nicho-consist-{suf}", status, projeto_uuid,
    )
    ids = {}
    for kw, kw_type in kws:
        ids[kw] = await lg.fetchval(
            """INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, status)
               VALUES ($1::uuid, $2, $3, 'pending') RETURNING id""",
            str(pid), f"{kw}-{suf}", kw_type,
        )
    return str(pid), ids


async def _limpar(pg, lg, projeto_uuid: str | None, pesquisa_ids: list[str]):
    """Filhos no Supabase primeiro, pesquisa e projeto no Postgres depois.

    Recebe os ids explicitamente (lição do Plan 35-05): redescobri-los pelo projeto
    devolveria vazio sempre que o teste falhasse depois de a pesquisa já ter sumido.
    """
    for pid in pesquisa_ids:
        await lg.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pid)
        await pg.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pid)
    if projeto_uuid:
        await pg.execute("DELETE FROM projetos WHERE id = $1::uuid", projeto_uuid)


async def _status_pesquisa(pg, pid: str) -> str:
    return await pg.fetchval("SELECT status FROM pesquisas WHERE id = $1::uuid", pid)


async def _status_kw(lg, kw_id: int) -> str:
    return await lg.fetchval("SELECT status FROM kw_staging WHERE id = $1", kw_id)


async def _conta_kw(lg, pid: str) -> int:
    return await lg.fetchval(
        "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid", pid
    )


def _cliente() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── Fluxo 1 — /approve: Supabase (fato) → Postgres (projeção) ───────────────


@pytest.mark.asyncio
async def test_fluxo1_approve_com_postgres_fora_avisa_e_converge(pg, lg, monkeypatch):
    """O Postgres cai DEPOIS do commit no Supabase. Estado conservador + cura.

    O que se exige:
      1. HTTP **200** com `aviso` em pt-BR — nunca um 500 mudo. O clique teve efeito
         parcial e o Board precisa saber disso na tela, não no log;
      2. `pesquisas_atualizadas` vazio;
      3. estado conservador: keyword `approved`, pesquisa ainda `classificado`. O
         pipeline não avança — jamais avança com dado errado;
      4. reexecutar converge: pesquisa `aprovado`, `approved: 0` (o bloco A vira
         no-op pelas guardas de idempotência) e a contagem de keywords não muda.
    """
    projeto, _ = await _seed_projeto(pg)
    pid, ids = await _seed_pesquisa(pg, lg, projeto, [("kw-f1", "SECAO")])
    try:
        _quebrar_postgres(monkeypatch, kw_module, await db_module.get_pool(), apos=1)

        async with _cliente() as c:
            r = await c.post(
                f"/projetos/{projeto}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approved"] == 1, body
        assert body["pesquisas_atualizadas"] == [], body
        assert "aviso" in body, "falha parcial silenciosa — o `aviso` sumiu da resposta"
        assert "reexecute" in body["aviso"].lower(), body["aviso"]
        assert set(body) == CHAVES_APPROVE | {"aviso"}

        # Estado nos DOIS bancos, lido por asyncpg — não pela API sob teste.
        assert await _status_kw(lg, ids["kw-f1"]) == "approved"
        assert await _status_pesquisa(pg, pid) == "classificado", (
            "a pesquisa avançou apesar de o passo do Postgres ter falhado"
        )

        # Cura: o Postgres volta e a mesma chamada converge, sem duplicar efeito.
        monkeypatch.undo()
        async with _cliente() as c:
            r2 = await c.post(
                f"/projetos/{projeto}/keywords/approve",
                json={"approve_all_non_descarta": True},
            )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["approved"] == 0, f"efeito duplicado na reexecução: {body2}"
        assert set(body2) == CHAVES_APPROVE, sorted(set(body2) ^ CHAVES_APPROVE)
        assert pid in body2["pesquisas_atualizadas"], body2
        assert await _status_pesquisa(pg, pid) == "aprovado"
        assert await _conta_kw(lg, pid) == 1
    finally:
        await _limpar(pg, lg, projeto, [pid])


# ── Fluxo 2 — POST /pesquisas/: Postgres (referenciado) → Supabase ──────────


@pytest.mark.asyncio
async def test_fluxo2_create_pesquisa_com_supabase_fora_nao_deixa_keyword_orfa(
    pg, lg, monkeypatch
):
    """A ordem inversa do `/approve`, provada por falha ENTRE as duas escritas.

    Se a ordem fosse a do `/approve` (Supabase primeiro), uma falha do Postgres
    deixaria keywords apontando para uma pesquisa que não existe — órfãs que nenhuma
    FK recusa mais, porque a FK cross-DB deixou de existir. Na ordem certa a janela
    produz o estado oposto e recuperável: a pesquisa existe **sem** keywords.

    A cura definida pela fase é a reexecução caindo no `UniqueViolationError` já
    tratado, que devolve 409 com o `pesquisa_id` existente — sem criar pesquisa
    duplicada. Ver a nota sobre o alcance dessa cura no 35-09-SUMMARY.md.
    """
    projeto, _ = await _seed_projeto(pg)
    suf = uuid.uuid4().hex[:8]
    payload = {
        "projeto_nome": f"Test-Consist-{suf}",
        "nicho": f"nicho-consist-{suf}",
        "cidade": "Brasília",
        "papel": "servico",
        "projeto_id": projeto,
        "keywords": [
            {"keyword": "kw f2 a", "kw_type": "PAGINA_PRINCIPAL"},
            {"keyword": "kw f2 b", "kw_type": "SERVICO"},
        ],
    }
    pid = None
    try:
        monkeypatch.setattr(review_module, "get_lg_pool", _pool_indisponivel)
        async with _cliente() as c:
            r = await c.post("/pesquisas/", json=payload)

        # Nunca um 500 mudo: a mensagem em pt-BR nomeia o efeito parcial e a cura.
        assert r.status_code == 500, r.text
        detalhe = r.json()["detail"]
        assert "pesquisa foi criada" in detalhe, detalhe
        assert "eexecute" in detalhe, detalhe

        # Etapa 1 durável: a pesquisa está no Postgres — prova de que ele veio antes.
        row = await pg.fetchrow(
            "SELECT id, status FROM pesquisas WHERE nicho = $1", payload["nicho"]
        )
        assert row is not None, (
            "a pesquisa não existe: o handler tocou o Supabase ANTES do Postgres "
            "— a ordem Postgres→Supabase foi invertida"
        )
        pid = str(row["id"])
        assert row["status"] == "classificado"

        # ...e nenhuma keyword órfã do outro lado.
        assert await _conta_kw(lg, pid) == 0

        # Cura: a reexecução cai no caminho de UniqueViolation, devolve o id
        # existente e NÃO cria uma segunda pesquisa.
        monkeypatch.undo()
        async with _cliente() as c:
            r2 = await c.post("/pesquisas/", json=payload)
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["pesquisa_id"] == pid
        assert await pg.fetchval(
            "SELECT COUNT(*) FROM pesquisas WHERE nicho = $1", payload["nicho"]
        ) == 1, "a reexecução criou uma pesquisa duplicada"

        # ⚠️ LACUNA CONHECIDA, medida e não presumida (D-35-09-01, ver 35-09-SUMMARY.md).
        # A cura devolve o `pesquisa_id` mas NÃO completa as keywords que faltaram: o
        # 409 é levantado dentro do `except UniqueViolationError`, antes da etapa 2.
        # Quem chama (`/kw-validator`) trata 409 como sucesso, então a pesquisa fica
        # permanentemente com 0 keywords — visível no Gate 2 (a lista mostra
        # `total_keywords: 0`), nunca corrompida, mas também nunca convergida sozinha.
        # Esta asserção existe para que a lacuna não some de vista: se ela falhar
        # porque alguém fez o caminho de conflito completar o insert, isso é uma
        # MELHORIA — atualize este bloco e o SUMMARY em vez de reverter o handler.
        assert await _conta_kw(lg, pid) == 0, (
            "a reexecução passou a gravar as keywords que faltavam — lacuna "
            "D-35-09-01 resolvida; atualizar este teste e o 35-09-SUMMARY.md"
        )
    finally:
        await _limpar(pg, lg, projeto, [pid] if pid else [])


# ── Fluxo 3 — approve-gate2: Supabase (fato) → Postgres (projeção) ──────────


@pytest.mark.asyncio
async def test_fluxo3_gate2_com_supabase_fora_nao_promove_a_pesquisa(
    pg, lg, monkeypatch, sem_bq
):
    """O caso que DISCRIMINA a ordem do Gate 1 — e o que o Plan 35-08 quase perdeu.

    Injetando falha no Postgres, as duas ordens possíveis produzem o mesmo estado
    final, porque o passo do Supabase roda de qualquer jeito: um teste montado assim
    passa sob a mutação que inverte a ordem e não prova nada. O caso discriminante é
    o Supabase fora — com a projeção antes do fato, a pesquisa ficaria `aprovado` com
    as keywords ainda `pending`: a tela diz "aprovado" e o `/seo-architect` não vê
    nada em `approved`. É textualmente o bug histórico que a docstring do endpoint
    descreve.
    """
    projeto, _ = await _seed_projeto(pg)
    pid, ids = await _seed_pesquisa(
        pg, lg, projeto,
        [("kw-f3-a", "PAGINA_PRINCIPAL"), ("kw-f3-b", "SERVICO"), ("kw-f3-lixo", "DESCARTA")],
    )
    try:
        monkeypatch.setattr(review_module, "get_lg_pool", _pool_indisponivel)
        async with _cliente() as c:
            r = await c.post(f"/pesquisas/{pid}/approve-gate2")
        monkeypatch.undo()

        assert r.status_code == 500, r.text
        assert "NÃO foi promovida" in r.json()["detail"], r.text

        # NADA foi aplicado, nos dois bancos.
        assert await _status_pesquisa(pg, pid) == "classificado", (
            "a pesquisa foi promovida sem as keywords terem sido aprovadas — "
            "a ordem fato→projeção foi invertida"
        )
        assert await lg.fetchval(
            "SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = $1::uuid "
            "AND status = 'pending'",
            pid,
        ) == 3
    finally:
        await _limpar(pg, lg, projeto, [pid])


@pytest.mark.asyncio
async def test_fluxo3_gate2_com_postgres_fora_avisa_e_converge(
    pg, lg, monkeypatch, sem_bq
):
    """Postgres cai ENTRE o fato e a projeção: 200 com `aviso`, e a reexecução cura.

    A DESCARTA fica de fora da aprovação nas duas passagens — é a guarda que impede
    o gate de arrastar keyword descartada para o `/seo-architect`.
    """
    projeto, _ = await _seed_projeto(pg)
    pid, ids = await _seed_pesquisa(
        pg, lg, projeto,
        [("kw-f4-a", "PAGINA_PRINCIPAL"), ("kw-f4-b", "SERVICO"), ("kw-f4-lixo", "DESCARTA")],
    )
    try:
        # `apos=1`: a 1ª aquisição é a resolução da pesquisa (pré-condição do gate);
        # da 2ª em diante é a projeção.
        _quebrar_postgres(monkeypatch, review_module, await db_module.get_pool(), apos=1)

        async with _cliente() as c:
            r = await c.post(f"/pesquisas/{pid}/approve-gate2")

        assert r.status_code == 200, r.text
        body = r.json()
        assert "aviso" in body, "falha parcial silenciosa — o `aviso` sumiu da resposta"
        assert "reexecute" in body["aviso"].lower(), body["aviso"]
        assert body["keywords_aprovadas"] == 2, body

        # O fato está gravado; a projeção, não.
        assert await _status_kw(lg, ids["kw-f4-a"]) == "approved"
        assert await _status_kw(lg, ids["kw-f4-b"]) == "approved"
        assert await _status_kw(lg, ids["kw-f4-lixo"]) == "pending"
        assert await _status_pesquisa(pg, pid) == "classificado"

        # Cura: reexecutar converge sem duplicar efeito — a guarda `status='pending'`
        # faz o passo 1 virar no-op.
        monkeypatch.undo()
        async with _cliente() as c:
            r2 = await c.post(f"/pesquisas/{pid}/approve-gate2")
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["keywords_aprovadas"] == 0, f"efeito duplicado: {body2}"
        assert "aviso" not in body2, body2
        assert await _status_pesquisa(pg, pid) == "aprovado"
        assert await _status_kw(lg, ids["kw-f4-lixo"]) == "pending"
    finally:
        await _limpar(pg, lg, projeto, [pid])


# ── T-35-12 — o arquivo não deixa resíduo nos dois bancos ───────────────────


@pytest.mark.asyncio
async def test_sem_residuo_dos_testes_deste_arquivo(pg, lg):
    """Roda por último (ordem do arquivo) e confere o teardown dos anteriores.

    Este arquivo escreve e falha de propósito contra bancos reais. Sem esta
    checagem, um `finally` incompleto acumularia projeto/pesquisa/keyword de teste
    em produção a cada execução — e a segunda execução seguida veria dado da
    primeira.
    """
    assert await pg.fetchval(
        "SELECT COUNT(*) FROM projetos WHERE projeto_nome LIKE 'Test-Consist-%'"
    ) == 0
    assert await pg.fetchval(
        "SELECT COUNT(*) FROM pesquisas WHERE nicho LIKE 'nicho-consist-%'"
    ) == 0
    assert await lg.fetchval(
        "SELECT COUNT(*) FROM kw_staging WHERE keyword LIKE 'kw-f%'"
    ) == 0
