"""REQ-8-03 — POST /projetos/{projeto_id}/keywords/approve-classified.
KWMGMT-05 — GET /projetos/{projeto_id}/keywords com filtros combináveis e paginação.
GATE-KW-01 — POST /projetos/{projeto_id}/keywords/approve (Gate do Board no dashboard).

Auth via middleware HTTP (main.py). Não usa Depends(require_api_key) — decisão D-09.

── Nota histórica (bug 2026-08-03) ───────────────────────────────────────────
`approve_classified_keywords` filtrava pesquisas só por `p.projeto_id = <INT legado>`.
Como `POST /pesquisas/` só popula `projeto_id_uuid`, o filtro casava zero linhas em
todo projeto criado após a migração UUID (Phase 05) — retornando HTTP 200 com
{"approved": 0} sem erro algum. As keywords ficavam presas em 'pending' e o rank
tracking (que filtra status='approved') coletava zero keywords do projeto.
Os testes não pegaram porque o fixture seedava projeto_id INT explicitamente.

Correção: todo filtro por projeto casa `projeto_id_uuid = $uuid OR projeto_id = $int`.
Migration 032 reparou os dados existentes.

## Fase 35 / D-02 e D-06 — `kw_staging` mora no Supabase, `pesquisas` fica no Postgres
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Este é o arquivo que mais atravessa a fronteira dos dois bancos, e o único da fase que
**escreve** nos dois. O antigo `_where_projeto()` — fragmento SQL que casava a pesquisa
pelo UUID ou pelo INT legado dentro de um JOIN `kw_staging × pesquisas` — não existe
mais: a mesma semântica vive em `_common._pesquisas_do_projeto()`, que roda no Postgres
e devolve a lista de `pesquisa_id`. Do lado do Supabase toda query filtra por
`pesquisa_id = ANY($1::uuid[])` com parâmetro posicional — nunca por concatenação de ids
(T-35-06) e nunca por valor vindo do corpo da requisição (T-35-05).

A estratégia de consistência do Gate (fato→projeção, sem outbox e sem compensação) está
no docstring de `approve_keywords_plan`.
"""

import sys

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import get_pool
from db_leadgen import get_lg_pool
from routers._common import _pesquisas_do_projeto, _resolve_projeto
from routers.kw_mgmt import ALLOWED_KW_TYPES

router = APIRouter(prefix="/projetos", tags=["keywords"])

# Status de pesquisa que o Board considera revisável/aprovável.
PESQUISA_STATUS_REVISAVEL = ("classificado", "aprovado")


def _listagem_vazia() -> dict:
    """Payload de GET /keywords quando nenhuma pesquisa do projeto entra no filtro.

    Devolvido **sem tocar no Supabase** — o `= ANY(ARRAY[]::uuid[])` casaria zero linhas
    de qualquer jeito, e não abrir o pool mantém 404/422 independentes do Supabase estar
    de pé. Instância nova a cada chamada: dicionário de módulo compartilhado é mutável.
    """
    return {"total": 0, "items": [], "resumo": {"por_status": {}, "por_kw_type": {}}}


def _e_uuid_malformado(e: Exception) -> bool:
    """Distingue 'o parâmetro não é UUID' de qualquer outra falha do banco.

    Duas formas aparecem, e o código antigo só reconhecia a primeira:
      - `invalid input syntax for type uuid` — o servidor rejeitou o texto;
      - `invalid input for query argument $N: ... (invalid UUID ...)` — o **asyncpg**
        rejeitou no bind, antes de ir à rede, porque o cast `::uuid` deixa o tipo do
        parâmetro conhecido. É o caso real de `?pesquisa_id=nao-e-uuid`, que respondia
        500 (medido antes da Fase 35).
    Mesma forma adotada em `kw_mgmt.py` e `intel.py`.
    """
    msg = str(e).lower()
    return "invalid input syntax" in msg or "invalid uuid" in msg


class ReclassifyItem(BaseModel):
    keyword_id: int
    kw_type: str


class ApprovePlanRequest(BaseModel):
    """Gate do Board: aprova o plano de keywords do projeto em uma transação.

    Precedência: reclassify → reject → approve. Assim o Board pode, no mesmo
    clique, mudar o tipo de uma keyword e já aprová-la com o tipo novo.
    """

    reclassify: list[ReclassifyItem] = Field(default_factory=list, max_length=5000)
    approve_ids: list[int] = Field(default_factory=list, max_length=5000)
    reject_ids: list[int] = Field(default_factory=list, max_length=5000)
    approve_all_non_descarta: bool = False
    aprovar_pesquisas: bool = True


@router.get("/{projeto_id}/keywords")
async def list_projeto_keywords(
    projeto_id: str,
    status: str | None = Query(
        default=None,
        description="Valor exato ou '!VALOR' para negação (ex.: '!approved')",
    ),
    kw_type: str | None = Query(
        default=None,
        description="Aceita valor exato ou '!VALOR' para negação (ex.: '!DESCARTA')",
    ),
    pesquisa_id: str | None = Query(default=None),
    papel: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Busca parcial no texto da keyword"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Lista keywords de um projeto com filtros combináveis e paginação (KWMGMT-05).

    Filtros:
    - status: valor exato OU '!VALOR' para negação (ex.: 'pending', '!approved')
    - kw_type: valor exato OU '!VALOR' para negação (ex.: '!DESCARTA')
    - pesquisa_id: UUID da pesquisa de origem
    - papel: papel da pesquisa (ex.: 'principal', 'servico')
    - q: busca ILIKE parcial no texto da keyword
    - limit/offset: paginação (default 100/0)

    Retorna: {total, items, resumo: {por_status, por_kw_type}}
    O resumo ignora limit/offset — é a contagem do filtro inteiro, que a tela
    do Board usa para os contadores das abas sem precisar paginar tudo.

    ## Fase 35 / D-02 — duas consultas e um casamento em memória
    O JOIN `kw_staging × pesquisas` deixou de ser possível. Passo 1 no Postgres:
    quais pesquisas do projeto entram (é aqui que o filtro `papel` passa a agir, porque
    `papel` é coluna de `pesquisas`). Passo 2 no Supabase: as keywords dessas pesquisas,
    com os filtros de `kw_staging`, o `total`, o `ORDER BY` e a paginação intactos em
    SQL. As colunas que vinham do JOIN são preenchidas em memória, **na mesma posição**
    do SELECT — a ordem das chaves do item é contrato observável (SC-01).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        # `statuses=None`: este endpoint nunca filtrou por status de pesquisa.
        pmap = await _pesquisas_do_projeto(conn, projeto_id, proj["id_int_legado"])

    if papel:
        pmap = {pid: row for pid, row in pmap.items() if row["papel"] == papel}

    if not pmap:
        return _listagem_vazia()

    # $1 é sempre a lista de pesquisas; os filtros dinâmicos começam em $2.
    where = ["ks.pesquisa_id = ANY($1::uuid[])"]
    params: list = [list(pmap.keys())]
    n = 2

    if status:
        if status.startswith("!"):
            where.append(f"ks.status <> ${n}")
            params.append(status[1:])
        else:
            where.append(f"ks.status = ${n}")
            params.append(status)
        n += 1

    if kw_type:
        # Case-insensitive dos dois lados: projetos legacy gravaram kw_type
        # em lowercase ('principal', 'geo'…) antes da normalização.
        if kw_type.startswith("!"):
            where.append(f"UPPER(COALESCE(ks.kw_type, '')) <> UPPER(${n})")
            params.append(kw_type[1:])
        else:
            where.append(f"UPPER(COALESCE(ks.kw_type, '')) = UPPER(${n})")
            params.append(kw_type)
        n += 1

    if pesquisa_id:
        # `pesquisa_id` é coluna da própria `kw_staging` — continua no SQL do Supabase.
        # A interseção com `ANY($1)` reproduz o que o JOIN garantia: um id de outro
        # projeto simplesmente não casa (T-35-05).
        where.append(f"ks.pesquisa_id = ${n}::uuid")
        params.append(pesquisa_id)
        n += 1

    if q:
        where.append(f"ks.keyword ILIKE ${n}")
        params.append(f"%{q}%")
        n += 1

    where_sql = " AND ".join(where)
    base_from = "FROM kw_staging ks"

    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        try:
            total = await c_lg.fetchval(
                f"SELECT COUNT(*) {base_from} WHERE {where_sql}", *params
            )

            rows = await c_lg.fetch(
                f"""SELECT ks.id, ks.keyword, ks.kw_type, ks.status,
                           ks.avg_monthly_searches, ks.competition, ks.competition_index,
                           ks.bid_pos5_8_brl, ks.bid_pos1_4_brl, ks.score, ks.go_nogo,
                           ks.competitive_score, ks.difficulty_label, ks.board_note,
                           ks.pesquisa_id::text AS pesquisa_id, NULL::text AS papel,
                           NULL::text AS nicho, NULL::text AS pesquisa_status
                    {base_from}
                   WHERE {where_sql}
                   ORDER BY ks.avg_monthly_searches DESC NULLS LAST, ks.id ASC
                   LIMIT ${n} OFFSET ${n + 1}""",
                *params, limit, offset,
            )

            resumo_status = await c_lg.fetch(
                f"SELECT ks.status, COUNT(*) AS n {base_from} WHERE {where_sql} GROUP BY 1",
                *params,
            )
            resumo_tipo = await c_lg.fetch(
                f"""SELECT UPPER(COALESCE(ks.kw_type, '')) AS kw_type, COUNT(*) AS n
                    {base_from} WHERE {where_sql} GROUP BY 1""",
                *params,
            )
        except Exception as e:
            if _e_uuid_malformado(e):
                raise HTTPException(422, "pesquisa_id não é um UUID válido")
            raise

    # As 4 colunas que o JOIN trazia: `pesquisa_id` já veio de `kw_staging`; as outras
    # três vêm do dicionário do Postgres. `.get()` porque, sem FK cross-DB, uma keyword
    # órfã deixou de ser impossível — melhor devolver nulo do que estourar KeyError.
    vazio: dict = {}
    items = []
    for r in rows:
        item = dict(r)
        pesq = pmap.get(item["pesquisa_id"], vazio)
        item["papel"] = pesq.get("papel")
        item["nicho"] = pesq.get("nicho")
        item["pesquisa_status"] = pesq.get("status")
        items.append(item)

    return {
        "total": total,
        "items": items,
        "resumo": {
            "por_status": {r["status"]: r["n"] for r in resumo_status},
            "por_kw_type": {r["kw_type"]: r["n"] for r in resumo_tipo},
        },
    }


@router.post("/{projeto_id}/keywords/approve")
async def approve_keywords_plan(projeto_id: str, body: ApprovePlanRequest):
    """Gate do Board — aprova o plano de keywords do projeto (GATE-KW-01).

    Substitui o `approve-classified` disparado às cegas pelo `/seo-architect`:
    aqui quem decide é o Board, no dashboard, com seleção explícita.

    Ordem (importa):
      1. reclassify — muda kw_type das keywords indicadas
      2. reject     — marca status='rejected'
      3. approve    — marca status='approved' (pula kw_type=DESCARTA)
      4. pesquisas  — sobe 'classificado' → 'aprovado' nas pesquisas tocadas

    Modo explícito (approve_ids) ou em massa (approve_all_non_descarta=true).
    Se ambos vierem vazios/false, nada é aprovado — mas reclassify/reject ainda
    são aplicados, o que permite usar o endpoint só para editar.

    IDs que não pertencem ao projeto voltam em `not_found` e não quebram o lote.

    ## Fase 35 / D-06 — fato primeiro, projeção depois
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    Os passos 1-3 escrevem em `kw_staging` (Supabase); o passo 4 escreve em `pesquisas`
    (Postgres). A transação única que cobria os quatro não existe mais, e não há 2PC
    entre os dois bancos. O que dispensa outbox e saga aqui é uma propriedade do próprio
    passo 4: `pesquisas.status` é uma **projeção pura** do estado de `kw_staging` — o SQL
    original já dizia `SET 'aprovado' ... WHERE status='classificado' AND EXISTS (kw
    aprovada)`. Não é dado independente; é recomputável a partir do fato.

    Daí a ordenação:
      Bloco 0 — Postgres, leitura. Resolve projeto e pesquisas. Nenhuma escrita.
      Bloco A — Supabase, o FATO. Os passos 1-3 inteiros dentro de UMA transação: ou os
                três acontecem, ou nenhum. Essa é a atomicidade que realmente importa.
      Bloco B — Postgres, a PROJEÇÃO, fora da transação do Supabase.

    Falha do bloco A: nada mudou nos dois bancos (rollback). Reclicar resolve.
    Falha do bloco B **depois** de A commitado: `kw_staging` aprovada e `pesquisas` ainda
    em 'classificado' — falha na direção conservadora (o pipeline não avança; jamais
    avança com dado errado). A resposta é **200 com `pesquisas_atualizadas: []` e um
    campo `aviso`**, nunca um 500 mudo: o Board precisa saber que o clique teve efeito
    parcial. A cura é reexecutar o mesmo endpoint — o bloco A vira no-op pelas guardas
    `status <> 'approved'` / `status <> 'rejected'` / `status = 'pending'`, e o bloco B
    roda de novo sobre o `WHERE status='classificado'`, que também é idempotente.

    **Nunca compensar.** Desfazer o approve no Supabase quando B falha é mais arriscado
    do que deixar o estado conservador e reexecutar.
    """
    # ── Bloco 0 — Postgres: resolve o projeto e suas pesquisas. Nenhuma escrita. ──
    # Duas listas, e a diferença entre elas não é detalhe: a aprovação só alcança as
    # pesquisas revisáveis, mas `skipped_descarta` e `pending_restantes` sempre contaram
    # sobre TODAS as pesquisas do projeto (o SQL original não filtrava status nessas
    # duas). Usar a lista errada muda contagem que o Board lê na tela.
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pmap = await _pesquisas_do_projeto(conn, projeto_id, proj["id_int_legado"])

    ids_projeto = list(pmap.keys())
    ids_revisaveis = [
        pid for pid, row in pmap.items() if row["status"] in PESQUISA_STATUS_REVISAVEL
    ]

    not_found: list[int] = []
    invalid: list[dict] = []

    # ── Bloco A — Supabase: o FATO, os 3 passos numa transação só ──
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        async with c_lg.transaction():
            # Universo de keywords do projeto (id → kw_type atual). Sem FK cross-DB,
            # esta lista — derivada do projeto resolvido no Postgres — é o que impede um
            # `keyword_id` forjado no corpo atingir keyword de outro projeto (T-35-05).
            owned_rows = await c_lg.fetch(
                """SELECT ks.id, UPPER(COALESCE(ks.kw_type, '')) AS kw_type
                     FROM kw_staging ks
                    WHERE ks.pesquisa_id = ANY($1::uuid[])""",
                ids_revisaveis,
            )
            owned: dict[int, str] = {r["id"]: r["kw_type"] for r in owned_rows}

            # ── 1. Reclassificar ──
            # Em lote: o laço item a item emitia um `execute` por keyword, e o contrato
            # aceita `max_length=5000`. Com o banco em localhost era barato; depois do
            # corte cada volta atravessa a internet (Pitfall 8).
            reclassified = 0
            lote_reclassify: dict[int, str] = {}
            for item in body.reclassify:
                if item.kw_type not in ALLOWED_KW_TYPES:
                    invalid.append({
                        "id": item.keyword_id,
                        "reason": f"kw_type inválido: '{item.kw_type}'. "
                                  f"Aceitos: {sorted(ALLOWED_KW_TYPES)}",
                    })
                    continue
                if item.keyword_id not in owned:
                    not_found.append(item.keyword_id)
                    continue
                # Deduplicação mantendo a ÚLTIMA ocorrência — é o estado que o laço
                # deixava no banco. `reclassified` continua contando por item, inclusive
                # os repetidos, como antes.
                lote_reclassify[item.keyword_id] = item.kw_type
                owned[item.keyword_id] = item.kw_type.upper()
                reclassified += 1
            if lote_reclassify:
                await c_lg.execute(
                    """UPDATE kw_staging
                          SET kw_type = t.tipo, updated_at = NOW()
                         FROM unnest($1::int[], $2::text[]) AS t(id, tipo)
                        WHERE kw_staging.id = t.id
                          AND kw_staging.pesquisa_id = ANY($3::uuid[])""",
                    list(lote_reclassify.keys()),
                    list(lote_reclassify.values()),
                    ids_revisaveis,
                )

            # ── 2. Rejeitar ──
            reject_ok = [i for i in body.reject_ids if i in owned]
            not_found.extend(i for i in body.reject_ids if i not in owned)
            rejected = 0
            if reject_ok:
                result = await c_lg.execute(
                    """UPDATE kw_staging SET status = 'rejected', updated_at = NOW()
                        WHERE id = ANY($1::int[]) AND status <> 'rejected'
                          AND pesquisa_id = ANY($2::uuid[])""",
                    reject_ok, ids_revisaveis,
                )
                rejected = int(result.split()[-1])

            # ── 3. Aprovar ──
            skipped_descarta = 0
            approved = 0
            if body.approve_all_non_descarta:
                result = await c_lg.execute(
                    """UPDATE kw_staging SET status = 'approved', updated_at = NOW()
                        WHERE pesquisa_id = ANY($1::uuid[])
                          AND status = 'pending'
                          AND UPPER(COALESCE(kw_type, '')) <> 'DESCARTA'""",
                    ids_revisaveis,
                )
                approved = int(result.split()[-1])
                skipped_descarta = await c_lg.fetchval(
                    """SELECT COUNT(*) FROM kw_staging
                        WHERE pesquisa_id = ANY($1::uuid[])
                          AND status = 'pending'
                          AND UPPER(COALESCE(kw_type, '')) = 'DESCARTA'""",
                    ids_projeto,
                ) or 0
            elif body.approve_ids:
                aprovaveis: list[int] = []
                for kid in body.approve_ids:
                    if kid not in owned:
                        not_found.append(kid)
                    elif owned[kid] == "DESCARTA":
                        skipped_descarta += 1
                    else:
                        aprovaveis.append(kid)
                if aprovaveis:
                    result = await c_lg.execute(
                        """UPDATE kw_staging SET status = 'approved', updated_at = NOW()
                            WHERE id = ANY($1::int[]) AND status <> 'approved'
                              AND pesquisa_id = ANY($2::uuid[])""",
                        aprovaveis, ids_revisaveis,
                    )
                    approved = int(result.split()[-1])

            # ── Candidatas à projeção e saldo — ainda dentro da transação do fato ──
            # Substituem o `EXISTS (SELECT 1 FROM kw_staging ...)` do UPDATE original e o
            # COUNT que fechava o handler; as duas contam sobre TODAS as pesquisas.
            aprovadas_rows = await c_lg.fetch(
                """SELECT DISTINCT pesquisa_id FROM kw_staging
                    WHERE pesquisa_id = ANY($1::uuid[]) AND status = 'approved'""",
                ids_projeto,
            )
            pending_restantes = await c_lg.fetchval(
                """SELECT COUNT(*) FROM kw_staging
                    WHERE pesquisa_id = ANY($1::uuid[])
                      AND status = 'pending'
                      AND UPPER(COALESCE(kw_type, '')) <> 'DESCARTA'""",
                ids_projeto,
            ) or 0

    # ── Bloco B — Postgres: a PROJEÇÃO, fora da transação do Supabase ──
    pesquisas_atualizadas: list[str] = []
    aviso: str | None = None
    if body.aprovar_pesquisas and (approved or body.approve_all_non_descarta):
        candidatas = [str(r["pesquisa_id"]) for r in aprovadas_rows]
        try:
            async with pool.acquire() as c_pg:
                rows = await c_pg.fetch(
                    """UPDATE pesquisas SET status = 'aprovado', reviewed_at = NOW()
                        WHERE id = ANY($1::uuid[]) AND status = 'classificado'
                    RETURNING id""",
                    candidatas,
                )
            pesquisas_atualizadas = [str(r["id"]) for r in rows]
        except Exception as e:
            # Nunca falhar mudo: as keywords JÁ estão aprovadas no Supabase. Sem o nome
            # da exceção crua nem a connection string na mensagem (T-35-08).
            print(
                f"[keywords] WARN: keywords do projeto {projeto_id} aprovadas no Supabase "
                f"mas a promoção das pesquisas no Postgres falhou: {type(e).__name__}",
                file=sys.stderr,
            )
            aviso = (
                "As keywords foram aprovadas, mas a sincronização do status das pesquisas "
                "ficou pendente. Reexecute a aprovação para concluir — a operação é "
                "idempotente e não duplica efeito."
            )

    resposta = {
        "approved": approved,
        "rejected": rejected,
        "reclassified": reclassified,
        "skipped_descarta": int(skipped_descarta),
        "pending_restantes": int(pending_restantes),
        "pesquisas_atualizadas": pesquisas_atualizadas,
        "not_found": sorted(set(not_found)),
        "invalid": invalid,
    }
    # `aviso` só existe no caminho degradado — no caminho feliz a resposta tem
    # exatamente as 8 chaves de sempre, nem uma a mais (SC-01).
    if aviso:
        resposta["aviso"] = aviso
    return resposta


@router.post("/{projeto_id}/keywords/approve-classified")
async def approve_classified_keywords(projeto_id: str):
    """Bulk approve das kw_staging pending (kw_type != 'DESCARTA') do projeto.

    Mantido para compatibilidade com scripts/agentes que já chamavam o path.
    O caminho canônico do Board agora é `POST /projetos/{id}/keywords/approve`.

    Filtro: pesquisa vinculada ao projeto por UUID **ou** INT legado, com
    status IN ('classificado', 'aprovado'), kw_staging.status = 'pending' e
    UPPER(kw_type) != 'DESCARTA'.

    Idempotente: rerun encontra 0 rows em pending → approved=0.

    ## Fase 35 / D-02 — mesmo recorte do `/approve`, sem o bloco de projeção
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    Este caminho legado nunca escreveu em `pesquisas` — `pesquisas_atualizadas` aqui é a
    lista das pesquisas *afetadas*, não das promovidas. Depois do corte ele é, portanto,
    uma escrita single-DB no Supabase precedida de uma leitura no Postgres: não há falha
    parcial cross-DB a tratar.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pmap = await _pesquisas_do_projeto(
            conn, projeto_id, proj["id_int_legado"], list(PESQUISA_STATUS_REVISAVEL)
        )
    ids = list(pmap.keys())

    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        async with c_lg.transaction():
            # Descobre pesquisas afetadas (antes do UPDATE — depois seriam approved)
            pesquisas_rows = await c_lg.fetch(
                """SELECT DISTINCT k.pesquisa_id
                     FROM kw_staging k
                    WHERE k.pesquisa_id = ANY($1::uuid[])
                      AND k.status = 'pending'
                      AND UPPER(COALESCE(k.kw_type, '')) != 'DESCARTA'""",
                ids,
            )
            pesquisas_atualizadas = [str(r["pesquisa_id"]) for r in pesquisas_rows]

            # Conta DESCARTA pendentes (skipped)
            skipped = await c_lg.fetchval(
                """SELECT COUNT(*) FROM kw_staging k
                    WHERE k.pesquisa_id = ANY($1::uuid[])
                      AND k.status = 'pending'
                      AND UPPER(COALESCE(k.kw_type, '')) = 'DESCARTA'""",
                ids,
            )

            # UPDATE em massa — pré-existência do filtro garante idempotência
            result = await c_lg.execute(
                """UPDATE kw_staging SET status = 'approved', updated_at = NOW()
                    WHERE pesquisa_id = ANY($1::uuid[])
                      AND status = 'pending'
                      AND UPPER(COALESCE(kw_type, '')) != 'DESCARTA'""",
                ids,
            )
            # asyncpg retorna "UPDATE N"
            approved = int(result.split()[-1])

    return {
        "approved": approved,
        "skipped_descarta": int(skipped or 0),
        "pesquisas_atualizadas": pesquisas_atualizadas,
    }
