import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, HTTPException
from google.cloud import bigquery
from google.oauth2 import service_account
from pydantic import BaseModel
from db import get_pool
from db_leadgen import get_lg_pool
from routers._common import _load_gcp_key

router = APIRouter(prefix="/pesquisas", tags=["review"])

_BQ_PROJECT = "gifted-slice-357413"
_BQ_SILVER_KW_PLAN = f"{_BQ_PROJECT}.leadgen_silver.kw_plan"
_BQ_GOLD_KW_PLAN = f"{_BQ_PROJECT}.leadgen_gold.kw_plan"
_BQ_SCOPES = ["https://www.googleapis.com/auth/bigquery"]
_bq_client: bigquery.Client | None = None


def _get_bq_client() -> bigquery.Client | None:
    """Retorna singleton BQ client ou None se GCP_SC_KEY não configurada.

    Aceita base64 (.env-prod) ou JSON single-line (worker/.env) via _load_gcp_key.
    """
    global _bq_client
    if _bq_client is not None:
        return _bq_client
    key_info = _load_gcp_key("GCP_SC_KEY")
    if not key_info:
        return None
    try:
        credentials = service_account.Credentials.from_service_account_info(
            key_info, scopes=_BQ_SCOPES
        )
        _bq_client = bigquery.Client(project=_BQ_PROJECT, credentials=credentials)
        return _bq_client
    except Exception as e:
        print(f"[WARN] Erro inicializando BQ client: {e}", file=sys.stderr)
        return None


def _insert_kw_plan_silver(client: bigquery.Client, rows: list[dict]) -> None:
    """INSERT síncrono em leadgen_silver.kw_plan — chamado via run_in_executor."""
    errors = client.insert_rows_json(_BQ_SILVER_KW_PLAN, rows)
    if errors:
        print(f"[WARN] BQ kw_plan silver errors: {errors}", file=sys.stderr)
    else:
        print(f"[bq] INSERT {len(rows)} rows em {_BQ_SILVER_KW_PLAN}")


def _insert_kw_plan_gold(client: bigquery.Client, rows: list[dict]) -> None:
    """INSERT síncrono em leadgen_gold.kw_plan — chamado via run_in_executor."""
    errors = client.insert_rows_json(_BQ_GOLD_KW_PLAN, rows)
    if errors:
        print(f"[WARN] BQ kw_plan gold errors: {errors}", file=sys.stderr)
    else:
        print(f"[bq] INSERT {len(rows)} rows em {_BQ_GOLD_KW_PLAN}")


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    score: float | None = None
    go_nogo: str | None = None
    board_note: str | None = None
    status: str | None = None
    kw_type: str | None = None


class ApproveRequest(BaseModel):
    approved_keywords: list[str]  # textos das keywords aprovadas


class KeywordInput(BaseModel):
    keyword: str
    kw_type: str  # PAGINA_PRINCIPAL | SERVICO | PAGINA_GEO | SECAO | DESCARTA
    avg_monthly_searches: int | None = None
    bid_pos5_8_brl: float | None = None
    bid_pos1_4_brl: float | None = None
    competition_index: float | None = None
    competition: str | int | None = None
    board_note: str | None = None


class PesquisaCreate(BaseModel):
    projeto_nome: str
    nicho: str
    cidade: str = "Brasília"
    geo_target_id: str | None = None
    papel: str | None = None  # 'principal' | 'servico' | None
    projeto_id: str | None = None  # UUID do projeto (opcional)
    avaliacao_json: dict | None = None
    seed_keywords: list[str] | None = None
    keywords: list[KeywordInput] = []
    skip_descarta: bool = True  # não insere kw_staging com kw_type=DESCARTA


# ── Fase 35 / D-02 — as duas queries de promoção, recompostas em memória ──────────
# ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md
#
# As duas eram `kw_staging JOIN pesquisas` (a segunda também `LEFT JOIN projetos`).
# `kw_staging` está no Supabase e `pesquisas`/`projetos` continuam no Postgres: o JOIN
# deixou de ser possível e vira UMA consulta de cada lado, casadas em memória.
#
# As colunas que vinham do JOIN continuam sendo selecionadas **na posição original** do
# SELECT, como NULL tipado, e são preenchidas depois. A ordem das chaves de cada linha é
# contrato observável (é ela que alimenta o dict de `rows_bq`), então não pode mudar.
#
# ⚠️ DOIS bugs pré-existentes corrigidos aqui, sem os quais nenhuma das duas queries
# executa (as duas levantam 500 em produção HOJE — medido contra o Postgres da VPS):
#   1. `ks.cpc_low_brl` / `ks.cpc_high_brl` não existem: a migration 016 as renomeou
#      para `bid_pos5_8_brl` / `bid_pos1_4_brl` e `review.py` nunca foi atualizado.
#      O alias devolve o nome antigo — é o nome do campo no schema do BigQuery, que
#      NÃO muda.
#   2. `LEFT JOIN projetos proj ON proj.id = p.projeto_id` compara `uuid = integer`
#      (`UndefinedFunctionError`): desde a Phase 05 o vínculo UUID é `projeto_id_uuid`.
_SQL_KW_PROMOCAO_GATE2 = """
    SELECT
        ks.keyword,
        ks.avg_monthly_searches,
        ks.competition,
        ks.competition_index,
        ks.bid_pos5_8_brl  AS cpc_low_brl,
        ks.bid_pos1_4_brl  AS cpc_high_brl,
        ks.score           AS opportunity_score,
        ks.go_nogo         AS recomendacao,
        ks.go_nogo         AS board_go_nogo,
        ks.board_note,
        ks.kw_type         AS tipo,
        NULL::text         AS pesquisa_id,
        NULL::text         AS nicho,
        NULL::text         AS cidade,
        NULL::text         AS geo_target_id,
        NULL::timestamptz  AS pesquisado_em,
        NULL::text         AS projeto_nome,
        NULL::text         AS projeto_url
    FROM kw_staging ks
    WHERE ks.pesquisa_id = $1::uuid
      AND UPPER(COALESCE(ks.kw_type, '')) != 'DESCARTA'
"""

_SQL_KW_PROMOCAO_GOLD = """
    SELECT
        ks.keyword,
        ks.avg_monthly_searches,
        ks.competition,
        ks.competition_index,
        ks.bid_pos5_8_brl  AS cpc_low_brl,
        ks.bid_pos1_4_brl  AS cpc_high_brl,
        ks.score           AS opportunity_score,
        ks.go_nogo         AS recomendacao,
        ks.kw_type         AS tipo,
        ks.competitive_score,
        ks.difficulty_label,
        ks.board_note,
        NULL::text         AS pesquisa_id,
        NULL::text         AS nicho,
        NULL::text         AS cidade,
        NULL::text         AS geo_target_id,
        NULL::text         AS projeto_nome,
        NULL::text         AS projeto_url
    FROM kw_staging ks
    WHERE ks.pesquisa_id = $1::uuid
      AND UPPER(COALESCE(ks.kw_type, '')) != 'DESCARTA'
"""

# A linha da pesquisa (+ o domínio do projeto) que o JOIN fornecia, agora do Postgres.
# O LEFT JOIN é preservado como LEFT JOIN: pesquisa sem projeto continua produzindo
# `projeto_url = None`, nunca um KeyError e nunca uma linha a menos.
_SQL_PESQUISA_PROMOCAO = """
    SELECT p.id::text AS pesquisa_id, p.nicho, p.cidade, p.geo_target_id,
           p.projeto_nome, p.created_at AS pesquisado_em,
           proj.metadata->>'dominio' AS projeto_url
      FROM pesquisas p
      LEFT JOIN projetos proj ON proj.id = p.projeto_id_uuid
     WHERE p.id = $1::uuid
"""


async def _kw_promocao(pesquisa_id: str, sql_kw: str, *, com_projeto_url: bool) -> list[dict]:
    """Recompõe em memória o que o JOIN cross-fronteira devolvia.

    Postgres primeiro (a pesquisa é a resolução; sem ela não há o que promover),
    Supabase depois — a mesma ordem de todos os handlers da fase.
    """
    pool = await get_pool()
    async with pool.acquire() as c_pg:
        pesquisa = await c_pg.fetchrow(_SQL_PESQUISA_PROMOCAO, pesquisa_id)
    if not pesquisa:
        # O JOIN (INNER, sobre pesquisas) já devolvia zero linhas neste caso.
        return []

    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        kw_rows = await c_lg.fetch(sql_kw, pesquisa_id)

    # `projeto_url` da query do Gate 2 sempre foi `NULL::text` literal — só a de gold
    # traz o domínio do projeto.
    do_join = {
        "pesquisa_id": pesquisa["pesquisa_id"],
        "nicho": pesquisa["nicho"],
        "cidade": pesquisa["cidade"],
        "geo_target_id": pesquisa["geo_target_id"],
        "pesquisado_em": pesquisa["pesquisado_em"],
        "projeto_nome": pesquisa["projeto_nome"],
        "projeto_url": pesquisa["projeto_url"] if com_projeto_url else None,
    }
    return [
        {k: (do_join[k] if k in do_join else v) for k, v in dict(r).items()}
        for r in kw_rows
    ]


async def _kw_gate2(pesquisa_id: str) -> list[dict]:
    """Keywords não-DESCARTA da pesquisa, no formato do espelho silver.kw_plan."""
    return await _kw_promocao(
        pesquisa_id, _SQL_KW_PROMOCAO_GATE2, com_projeto_url=False
    )


async def _kw_gold(pesquisa_id: str, _sem_filtro_go: bool = False) -> list[dict]:
    """Keywords GO da pesquisa, no formato do gold.kw_plan.

    `_sem_filtro_go` existe só para a conferência de paridade da Fase 35: hoje as 382
    linhas de `kw_staging` têm `go_nogo` NULL, então com o filtro nenhuma linha volta e
    a recomposição em memória não seria exercida por dado real. Nenhum handler usa.
    """
    sql = _SQL_KW_PROMOCAO_GOLD
    if not _sem_filtro_go:
        sql += "      AND ks.go_nogo = 'GO'\n"
    return await _kw_promocao(pesquisa_id, sql, com_projeto_url=True)


@router.post("/")
async def create_pesquisa(body: PesquisaCreate):
    """Cria a pesquisa no Postgres e as keywords no Supabase, nessa ordem.

    Usado pelo agente `/kw-validator` para persistir o resultado do
    kw_research + classificação. A pesquisa nasce com status='classificado'
    (kw-validator já classificou — Gate 2 no dashboard /kw-planner) e as
    keywords com status='pending'.

    ## Fase 35 / D-06 — a ordem aqui é o INVERSO da do `/approve`
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    Isto era **uma** transação: `pesquisas` (Postgres) e `kw_staging` (Supabase) hoje
    moram em bancos diferentes e não há transação atravessando a fronteira.

    Em `POST /projetos/{id}/keywords/approve` a ordem é Supabase→Postgres, porque lá o
    fato (a keyword aprovada) precede a projeção (o status da pesquisa). **Aqui é o
    contrário:** `kw_staging.pesquisa_id` *referencia* a pesquisa, então a pesquisa
    precisa existir primeiro. Copiar a ordem do `/approve` para cá gravaria keywords
    apontando para uma pesquisa que ainda não existe — órfãs invisíveis, já que a FK
    cross-DB também não existe mais para recusá-las.

    A falha da etapa 2 deixa a pesquisa **sem keywords**: estado visível (a resposta diz
    exatamente isso, em pt-BR) e curável reexecutando a mesma chamada, que cai no
    `UniqueViolationError` já tratado abaixo. É o mesmo caminho de cura que o retry do
    `/kw-validator` sempre teve.
    """
    pool = await get_pool()
    pesquisa_row = None
    inserted = 0

    # ── Etapa 1 — Postgres: a pesquisa. Nada é escrito no Supabase antes disto. ──
    async with pool.acquire() as conn:
        # Wrapper try captura UniqueViolation após o rollback automático da
        # transaction (asyncpg lança InFailedSQLTransactionError se tentarmos
        # SELECT dentro da txn abortada — por isso o SELECT fica fora).
        try:
            async with conn.transaction():
                # projeto_id (INT legado) precisa acompanhar o UUID. Endpoints
                # antigos (approve-classified, promote-gold) ainda filtram pelo
                # INT; deixá-lo NULL fazia esses filtros casarem zero linhas
                # silenciosamente — ver migration 032 e keywords.py.
                projeto_id_int = None
                if body.projeto_id:
                    projeto_id_int = await conn.fetchval(
                        "SELECT id_int_legado FROM projetos WHERE id = $1::uuid",
                        body.projeto_id,
                    )

                pesquisa_row = await conn.fetchrow(
                    """
                    INSERT INTO pesquisas (
                        projeto_nome, nicho, cidade, geo_target_id, status,
                        papel, projeto_id_uuid, projeto_id, avaliacao_json, seed_keywords
                    )
                    VALUES ($1, $2, $3, $4, 'classificado', $5, $6::uuid, $7::int, $8::jsonb, $9::jsonb)
                    RETURNING *
                    """,
                    body.projeto_nome,
                    body.nicho,
                    body.cidade,
                    body.geo_target_id,
                    body.papel,
                    body.projeto_id,
                    projeto_id_int,
                    json.dumps(body.avaliacao_json) if body.avaliacao_json is not None else None,
                    json.dumps(body.seed_keywords) if body.seed_keywords is not None else None,
                )
        except asyncpg.UniqueViolationError:
            # REQ-8-08 / CRIT-5: retry após timeout retorna 409 com pesquisa_id
            # existente para skill tratar como sucesso. A UNIQUE natural
            # pesquisas_natural_key cobre (nicho, cidade, projeto_id_uuid, papel).
            # A transaction já sofreu rollback automático via context manager
            # do asyncpg. Fase 35: com o INSERT de kw_staging movido para DEPOIS
            # deste bloco, o retry nem chega a tocar o Supabase — não há row órfã
            # a reverter (T5 do teste ficou estritamente mais forte).
            # IS NOT DISTINCT FROM trata NULL corretamente.
            existing = await conn.fetchrow(
                """SELECT id FROM pesquisas
                    WHERE nicho = $1
                      AND cidade = $2
                      AND projeto_id_uuid IS NOT DISTINCT FROM $3::uuid
                      AND papel IS NOT DISTINCT FROM $4""",
                body.nicho, body.cidade, body.projeto_id, body.papel,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Pesquisa já existe",
                    "pesquisa_id": str(existing["id"]) if existing else None,
                },
            )

    # ── Etapa 2 — Supabase: as keywords, já com o pesquisa_id que passou a existir. ──
    pesquisa_id = pesquisa_row["id"]
    kw_rows = [
        k for k in body.keywords
        if not (body.skip_descarta and k.kw_type == "DESCARTA")
    ]
    if kw_rows:
        values = []
        params: list = []
        for i, k in enumerate(kw_rows):
            base = i * 9
            values.append(
                f"(${base+1}::uuid, ${base+2}, ${base+3}, ${base+4}, "
                f"${base+5}, ${base+6}, ${base+7}, ${base+8}, ${base+9}, 'pending')"
            )
            params.extend([
                pesquisa_id,
                k.keyword,
                k.kw_type,
                k.avg_monthly_searches,
                k.bid_pos5_8_brl,
                k.bid_pos1_4_brl,
                k.competition_index,
                str(k.competition) if k.competition is not None else None,
                k.board_note,
            ])
        # Só os índices posicionais entram por f-string; todo valor do corpo viaja
        # em `params` (T-35-06). É o mesmo formato multi-VALUES de antes do corte.
        sql = (
            "INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, "
            "avg_monthly_searches, bid_pos5_8_brl, bid_pos1_4_brl, "
            "competition_index, competition, board_note, status) VALUES "
            + ", ".join(values)
        )
        try:
            lg = await get_lg_pool()
            async with lg.acquire() as c_lg:
                await c_lg.execute(sql, *params)
        except Exception as e:
            # Nunca falhar mudo: a pesquisa JÁ existe no Postgres, sem keywords.
            # Sem a exceção crua nem a connection string na mensagem (T-35-08).
            print(
                f"[review] WARN: pesquisa {pesquisa_id} criada no Postgres mas as "
                f"{len(kw_rows)} keywords não foram gravadas no Supabase: {type(e).__name__}",
                file=sys.stderr,
            )
            raise HTTPException(
                500,
                "A pesquisa foi criada, mas as keywords não foram gravadas. Reexecute a "
                "mesma chamada para concluir — a pesquisa já existente é devolvida em um "
                "409 com o seu pesquisa_id.",
            )
        inserted = len(kw_rows)

    return {
        "pesquisa": dict(pesquisa_row),
        "keywords_inseridas": inserted,
        "keywords_ignoradas_descarta": len(body.keywords) - inserted,
    }


@router.get("/{pesquisa_id}")
async def get_pesquisa(pesquisa_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        keywords = await conn.fetch(
            "SELECT * FROM kw_staging WHERE pesquisa_id = $1 ORDER BY score DESC NULLS LAST",
            pesquisa_id,
        )

    return {
        "pesquisa": dict(pesquisa),
        "keywords": [dict(k) for k in keywords],
        "total": len(keywords),
        "go_count": sum(1 for k in keywords if k["go_nogo"] == "GO"),
    }


@router.patch("/{pesquisa_id}/keywords/{keyword_id}")
async def update_keyword(pesquisa_id: str, keyword_id: int, body: KeywordUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        # Se kw_type está sendo alterado, lê o valor atual para logar o override
        if "kw_type" in fields:
            row = await conn.fetchrow(
                "SELECT keyword, kw_type FROM kw_staging WHERE id = $1 AND pesquisa_id = $2",
                keyword_id, pesquisa_id,
            )
            if row and row["kw_type"] is not None and row["kw_type"] != fields["kw_type"]:
                await conn.execute(
                    """INSERT INTO kw_classification_overrides
                       (pesquisa_id, keyword, classificacao_agente, classificacao_humana)
                       VALUES ($1, $2, $3, $4)""",
                    pesquisa_id, row["keyword"], row["kw_type"], fields["kw_type"],
                )

        set_clause = ", ".join(f"{k} = ${i+3}" for i, k in enumerate(fields))
        values = list(fields.values())

        await conn.execute(
            f"UPDATE kw_staging SET {set_clause} WHERE id = $1 AND pesquisa_id = $2",
            keyword_id, pesquisa_id, *values,
        )
    return {"ok": True}


@router.post("/{pesquisa_id}/auto-advance")
async def auto_advance_pesquisa(pesquisa_id: str):
    """Chamado pelo agente kw_research ao concluir — dispara kw_validator sem interação do Board."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        await conn.execute(
            "UPDATE pesquisas SET status = 'approved', reviewed_at = NOW() WHERE id = $1",
            pesquisa_id,
        )

        exec_id = await conn.fetchval(
            """INSERT INTO agent_executions
               (pesquisa_id, analysis_version, agent_name, status, started_at)
               VALUES ($1, 1, 'kw_validator', 'pending', NOW())
               RETURNING id""",
            pesquisa_id,
        )

    return {"ok": True, "agent_executions_id": str(exec_id)}


class ApproveGate2Request(BaseModel):
    projeto_id: str | None = None       # UUID — vincular a projeto existente
    criar_projeto: bool = False          # criar novo projeto a partir desta pesquisa


class PesquisaVincularUpdate(BaseModel):
    projeto_id: str | None = None      # UUID do projeto
    papel: str | None = None           # 'principal' | 'servico'
    servico_slug: str | None = None


@router.post("/{pesquisa_id}/approve-gate2")
async def approve_gate2(pesquisa_id: str, body: ApproveGate2Request = ApproveGate2Request()):
    """Gate do Board sobre UMA pesquisa: aprova a pesquisa E suas keywords.

    Até 2026-08-03 este endpoint só mexia em `pesquisas.status` — as keywords
    ficavam em kw_staging.status='pending' para sempre, porque o único lugar que
    as aprovava era o `/seo-architect` (via approve-classified, que estava quebrado
    pelo mesmo bug de projeto_id). Resultado: o Board "aprovava" e nada acontecia
    a jusante. Agora a aprovação da pesquisa arrasta as keywords não-DESCARTA.

    Para aprovação granular (seleção linha a linha, reclassificação, rejeição),
    usar `POST /projetos/{id}/keywords/approve`.
    """
    pool = await get_pool()
    keywords_aprovadas = 0
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        projeto_id = body.projeto_id

        # Criar novo projeto a partir da pesquisa (ou reusar se nome já existe)
        if body.criar_projeto and not projeto_id:
            nome = pesquisa["projeto_nome"] or pesquisa["nicho"]
            row = await conn.fetchrow(
                """INSERT INTO projetos (projeto_nome, nicho, cidade, status, pesquisa_id_atual)
                   VALUES ($1, $2, $3, 'research', $4)
                   ON CONFLICT (projeto_nome) DO UPDATE SET updated_at = NOW()
                   RETURNING id""",
                nome,
                pesquisa["nicho"],
                pesquisa["cidade"],
                pesquisa_id,
            )
            projeto_id = str(row["id"])

        # Vincular projeto existente à pesquisa atual
        if projeto_id:
            await conn.execute(
                "UPDATE projetos SET pesquisa_id_atual = $1, updated_at = NOW() WHERE id = $2::uuid",
                pesquisa_id, projeto_id,
            )

        async with conn.transaction():
            # Atualizar pesquisa — status 'aprovado' é o valor válido no check constraint.
            # O vínculo com o projeto só é reescrito quando um projeto foi informado:
            # a versão anterior fazia `SET projeto_id = $2` incondicionalmente e, com
            # body vazio (o caso do dashboard), ZERAVA o vínculo INT legado da pesquisa.
            if projeto_id:
                projeto_id_int = await conn.fetchval(
                    "SELECT id_int_legado FROM projetos WHERE id = $1::uuid", projeto_id
                )
                await conn.execute(
                    """UPDATE pesquisas
                       SET status = 'aprovado', reviewed_at = NOW(),
                           projeto_id_uuid = $2::uuid, projeto_id = $3::int
                       WHERE id = $1""",
                    pesquisa_id, projeto_id, projeto_id_int,
                )
            else:
                await conn.execute(
                    """UPDATE pesquisas
                       SET status = 'aprovado', reviewed_at = NOW()
                       WHERE id = $1""",
                    pesquisa_id,
                )

            # Gate de verdade: as keywords não-DESCARTA saem de 'pending'.
            result = await conn.execute(
                """UPDATE kw_staging
                      SET status = 'approved', updated_at = NOW()
                    WHERE pesquisa_id = $1::uuid
                      AND status = 'pending'
                      AND UPPER(COALESCE(kw_type, '')) <> 'DESCARTA'""",
                pesquisa_id,
            )
            keywords_aprovadas = int(result.split()[-1])

    # Gravar keywords aprovadas em BQ leadgen_silver.kw_plan (espelho — Postgres é fonte de verdade)
    bq = _get_bq_client()
    if bq:
        # Fase 35 / D-02: o JOIN cross-fronteira virou duas consultas casadas em memória.
        kw_rows = await _kw_gate2(pesquisa_id)

        promovido_em = datetime.now(timezone.utc).isoformat()
        rows_bq = []
        for row in kw_rows:
            d = dict(row)
            rows_bq.append({
                "pesquisa_id":          d["pesquisa_id"],
                "nicho":                d["nicho"],
                "cidade":               d["cidade"],
                "geo_target_id":        d.get("geo_target_id"),
                "pesquisado_em":        d["pesquisado_em"].isoformat() if d.get("pesquisado_em") else None,
                "keyword":              d["keyword"],
                "avg_monthly_searches": d.get("avg_monthly_searches"),
                "competition":          d.get("competition"),
                "competition_index":    d.get("competition_index"),
                "cpc_low_brl":          float(d["cpc_low_brl"]) if d.get("cpc_low_brl") else None,
                "cpc_high_brl":         float(d["cpc_high_brl"]) if d.get("cpc_high_brl") else None,
                "opportunity_score":    float(d["opportunity_score"]) if d.get("opportunity_score") else None,
                "recomendacao":         d.get("recomendacao"),
                "tipo":                 d.get("tipo"),
                "board_go_nogo":        d.get("board_go_nogo"),
                "board_note":           d.get("board_note"),
                "projeto_nome":         d.get("projeto_nome"),
                "projeto_url":          d.get("projeto_url"),
                "monthly_volumes":      None,
                "promovido_em":         promovido_em,
            })

        if rows_bq:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: _insert_kw_plan_silver(bq, rows_bq),
                )
            except Exception as e:
                print(f"[WARN] Erro gravando BQ silver.kw_plan: {e}", file=sys.stderr)

    return {
        "ok": True,
        "pesquisa_id": pesquisa_id,
        "status": "aprovado",
        "projeto_id": projeto_id,
        "keywords_aprovadas": keywords_aprovadas,
    }


@router.patch("/{pesquisa_id}/vincular")
async def vincular_pesquisa(pesquisa_id: str, body: PesquisaVincularUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not row:
            raise HTTPException(404, "Pesquisa não encontrada")

        if not any([body.projeto_id, body.papel, body.servico_slug]):
            raise HTTPException(400, "Nenhum campo para atualizar")

        # projeto_id chega como UUID — precisa atualizar as duas colunas:
        # projeto_id_uuid (UUID, lido por projetos.py) e projeto_id (int legado)
        if body.projeto_id:
            projeto = await conn.fetchrow(
                "SELECT id_int_legado FROM projetos WHERE id = $1", body.projeto_id
            )
            if not projeto:
                raise HTTPException(404, "Projeto não encontrado")
            await conn.execute(
                """UPDATE pesquisas
                   SET projeto_id_uuid = $2, projeto_id = $3
                   WHERE id = $1""",
                pesquisa_id, body.projeto_id, projeto["id_int_legado"],
            )

        # papel e servico_slug são atualizações simples de texto
        if body.papel or body.servico_slug:
            extra: dict = {}
            if body.papel:
                extra["papel"] = body.papel
            if body.servico_slug:
                extra["servico_slug"] = body.servico_slug
            set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(extra))
            await conn.execute(
                f"UPDATE pesquisas SET {set_clause} WHERE id = $1",
                pesquisa_id, *extra.values(),
            )

    return {"ok": True}


@router.delete("/{pesquisa_id}/vincular")
async def desvincular_pesquisa(pesquisa_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not row:
            raise HTTPException(404, "Pesquisa não encontrada")
        await conn.execute(
            "UPDATE pesquisas SET projeto_id = NULL, papel = NULL, servico_slug = NULL WHERE id = $1",
            pesquisa_id,
        )
    return {"ok": True}


@router.delete("/{pesquisa_id}/keywords/{keyword_id}")
async def delete_keyword(pesquisa_id: str, keyword_id: int):
    """Apaga UMA keyword da pesquisa.

    Fase 35 / D-02: `kw_staging` mora no Supabase — só a conexão mudou.

    O `AND pesquisa_id = $2` não é redundante: com a FK cross-DB removida, é ele que
    impede apagar a keyword de outra pesquisa passando um `keyword_id` alheio (T-35-05).
    Os DOIS predicados precisam continuar no WHERE — o 404 em pt-BR sai justamente de
    nenhuma linha ter sido afetada.
    """
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        result = await c_lg.execute(
            "DELETE FROM kw_staging WHERE id = $1 AND pesquisa_id = $2::uuid",
            keyword_id, pesquisa_id,
        )
    if result == "DELETE 0":
        raise HTTPException(404, "Keyword não encontrada")
    return {"ok": True}


# NOTE: DELETE /pesquisas/{id} movido para kw_mgmt.py (Phase 32-03) com guard + soft/hard toggle.

@router.post("/{pesquisa_id}/reject")
async def reject_pesquisa(pesquisa_id: str):
    """Rejeita a pesquisa e remove as keywords do staging.

    ## Fase 35 / D-06 — escrita cross-DB não prevista no ADR
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    Era um `DELETE FROM kw_staging` + `UPDATE pesquisas` na mesma conexão. As duas
    tabelas estão em bancos diferentes agora, então viram três etapas ordenadas:

    1. Postgres: resolve a pesquisa e devolve o 404 — validação **antes** de qualquer
       escrita, nos dois bancos.
    2. Supabase: apaga as keywords.
    3. Postgres: marca a pesquisa como rejeitada.

    Filhos primeiro, pela mesma razão dos outros deletes da fase (`DELETE /pesquisas/{id}`
    em kw_mgmt.py): a intenção do endpoint é destrutiva, então a falha do passo 3 deixa a
    pesquisa sem keywords e ainda não rejeitada — reexecutar converge, com o passo 2
    virando no-op. A ordem inversa deixaria keywords órfãs e permanentes, apontando para
    uma pesquisa rejeitada que ninguém mais visita.
    """
    pool = await get_pool()

    # Passo 1 — Postgres: resolução e 404. Nenhuma escrita aqui.
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

    # Passo 2 — Supabase: as keywords saem do staging.
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        await c_lg.execute(
            "DELETE FROM kw_staging WHERE pesquisa_id = $1::uuid", pesquisa_id
        )

    # Passo 3 — Postgres: só então a pesquisa vira 'rejected'.
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE pesquisas SET status = 'rejected', reviewed_at = NOW() WHERE id = $1",
                pesquisa_id,
            )
    except Exception as e:
        # Nunca falhar mudo: as keywords JÁ foram apagadas. Sem a exceção crua nem a
        # connection string na mensagem (T-35-08).
        print(
            f"[review] WARN: keywords da pesquisa {pesquisa_id} apagadas no Supabase mas "
            f"o UPDATE de status no Postgres falhou: {type(e).__name__}",
            file=sys.stderr,
        )
        raise HTTPException(
            500,
            "As keywords foram removidas do staging, mas a pesquisa não pôde ser marcada "
            "como rejeitada. Reexecute a rejeição para concluir — a operação é idempotente.",
        )

    return {"ok": True, "message": f"Pesquisa {pesquisa_id} rejeitada e removida do staging"}


@router.post("/{pesquisa_id}/promote-gold")
async def promote_gold(pesquisa_id: str):
    """Gate 2 do Board — promove keywords aprovadas para leadgen_gold.kw_plan.

    Requer que a pesquisa já esteja com status='aprovado' (Gate 1 concluído).
    Idealmente chamado após /competitive-intel ter enriquecido as keywords com
    competitive_score e difficulty_label.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        if pesquisa["status"] != "aprovado":
            raise HTTPException(
                400,
                f"Pesquisa não está com status 'aprovado' (status atual: {pesquisa['status']}) "
                "— realize o Gate 1 (approve-gate2) antes de promover para gold",
            )

    # Fase 35 / D-02: o JOIN cross-fronteira (que também alcançava `projetos`) virou
    # duas consultas casadas em memória. Fora do `async with` acima — o helper abre a
    # própria conexão em cada banco.
    kw_rows = await _kw_gold(pesquisa_id)

    aprovado_em = datetime.now(timezone.utc).isoformat()
    rows_bq = []
    for row in kw_rows:
        d = dict(row)
        rows_bq.append({
            "pesquisa_id":          d["pesquisa_id"],
            "nicho":                d["nicho"],
            "cidade":               d["cidade"],
            "geo_target_id":        d.get("geo_target_id"),
            "keyword":              d["keyword"],
            "avg_monthly_searches": d.get("avg_monthly_searches"),
            "competition":          d.get("competition"),
            "competition_index":    d.get("competition_index"),
            "cpc_low_brl":          float(d["cpc_low_brl"]) if d.get("cpc_low_brl") else None,
            "cpc_high_brl":         float(d["cpc_high_brl"]) if d.get("cpc_high_brl") else None,
            "opportunity_score":    float(d["opportunity_score"]) if d.get("opportunity_score") else None,
            "recomendacao":         d.get("recomendacao"),
            "tipo":                 d.get("tipo"),
            "competitive_score":    float(d["competitive_score"]) if d.get("competitive_score") else None,
            "difficulty_label":     d.get("difficulty_label"),
            "board_note":           d.get("board_note"),
            "projeto_nome":         d.get("projeto_nome"),
            "projeto_url":          d.get("projeto_url"),
            "gate2_status":         "go",
            "aprovado_em":          aprovado_em,
        })

    bq_status = "ok"
    bq = _get_bq_client()
    if bq and rows_bq:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: _insert_kw_plan_gold(bq, rows_bq),
            )
        except Exception as e:
            print(f"[WARN] Erro gravando BQ gold.kw_plan: {e}", file=sys.stderr)
            bq_status = "warn"
    elif not bq:
        bq_status = "warn"

    return {
        "ok": True,
        "pesquisa_id": pesquisa_id,
        "keywords_promovidas": len(rows_bq),
        "bq_status": bq_status,
    }


@router.get("/")
async def list_pesquisas():
    """As 50 pesquisas mais recentes, com a contagem de keywords de cada uma.

    Fase 35 / D-02: o `LEFT JOIN kw_staging` + `COUNT`/`GROUP BY` não cabe mais numa
    consulta só. As pesquisas vêm do Postgres com o `ORDER BY`/`LIMIT` intactos, a
    contagem vem do Supabase em UM round-trip (`= ANY($1::uuid[])`, nunca lista
    concatenada — T-35-06) e as duas se casam por dicionário.

    Dois round-trips com casamento em memória é precedente aceito no repo para
    agregação que não cabe numa consulta só (`fetchOfertasCounts` do LowTicket).

    `total_keywords` continua sendo a ÚLTIMA chave de cada linha e continua inteiro:
    pesquisa sem keyword devolve `0`, que é o que o `LEFT JOIN` + `COUNT` produzia —
    não `None`.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT p.* FROM pesquisas p ORDER BY p.created_at DESC LIMIT 50"
        )

    contagem: dict[str, int] = {}
    if rows:
        lg = await get_lg_pool()
        async with lg.acquire() as c_lg:
            totais = await c_lg.fetch(
                """SELECT pesquisa_id, COUNT(*) AS total
                     FROM kw_staging
                    WHERE pesquisa_id = ANY($1::uuid[])
                    GROUP BY pesquisa_id""",
                [r["id"] for r in rows],
            )
        contagem = {str(t["pesquisa_id"]): t["total"] for t in totais}

    return [
        {**dict(r), "total_keywords": contagem.get(str(r["id"]), 0)} for r in rows
    ]
