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
**escreve** nos dois. O `_where_projeto()` — fragmento SQL que casava a pesquisa pelo
UUID ou pelo INT legado dentro de um JOIN `kw_staging × pesquisas` — dá lugar a
`_common._pesquisas_do_projeto()`, que roda no Postgres e devolve a lista de
`pesquisa_id`. Do lado do Supabase toda query filtra por
`pesquisa_id = ANY($1::uuid[])` com parâmetro posicional — nunca por concatenação de ids
(T-35-06) e nunca por valor vindo do corpo da requisição (T-35-05).
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import get_pool
from db_leadgen import get_lg_pool
from routers._common import _pesquisas_do_projeto, _resolve_projeto
from routers.kw_mgmt import ALLOWED_KW_TYPES

router = APIRouter(prefix="/projetos", tags=["keywords"])

# Status de pesquisa que o Board considera revisável/aprovável.
PESQUISA_STATUS_REVISAVEL = ("classificado", "aprovado")


def _where_projeto(uuid_param: int, int_param: int) -> str:
    """Fragmento WHERE que casa a pesquisa pelo UUID OU pelo INT legado.

    Recebe os NÚMEROS dos placeholders asyncpg (ex.: 1 e 2 → "$1"/"$2").
    O INT pode ser NULL — `$2::int IS NOT NULL AND` protege o comparativo.

    Fase 35: só resta em uso no Gate de aprovação, migrado logo em seguida — some do
    arquivo quando o último JOIN cross-fronteira sair.
    """
    return (
        f"(p.projeto_id_uuid = ${uuid_param}::uuid"
        f" OR (${int_param}::int IS NOT NULL AND p.projeto_id = ${int_param}::int))"
    )


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

    Ordem dentro da transação (importa):
      1. reclassify — muda kw_type das keywords indicadas
      2. reject     — marca status='rejected'
      3. approve    — marca status='approved' (pula kw_type=DESCARTA)
      4. pesquisas  — sobe 'classificado' → 'aprovado' nas pesquisas tocadas

    Modo explícito (approve_ids) ou em massa (approve_all_non_descarta=true).
    Se ambos vierem vazios/false, nada é aprovado — mas reclassify/reject ainda
    são aplicados, o que permite usar o endpoint só para editar.

    IDs que não pertencem ao projeto voltam em `not_found` e não quebram o lote.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await _resolve_projeto(conn, projeto_id)
            pid_int = proj["id_int_legado"]
            where_proj = _where_projeto(1, 2)
            proj_params = [projeto_id, pid_int]

            # ── Universo de keywords do projeto (id → kw_type atual) ──
            owned_rows = await conn.fetch(
                f"""SELECT ks.id, UPPER(COALESCE(ks.kw_type, '')) AS kw_type
                      FROM kw_staging ks
                      JOIN pesquisas p ON p.id = ks.pesquisa_id
                     WHERE {where_proj}
                       AND p.status = ANY($3::text[])""",
                *proj_params, list(PESQUISA_STATUS_REVISAVEL),
            )
            owned: dict[int, str] = {r["id"]: r["kw_type"] for r in owned_rows}

            not_found: list[int] = []
            invalid: list[dict] = []

            # ── 1. Reclassificar ──
            reclassified = 0
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
                await conn.execute(
                    "UPDATE kw_staging SET kw_type = $1, updated_at = NOW() WHERE id = $2",
                    item.kw_type, item.keyword_id,
                )
                owned[item.keyword_id] = item.kw_type.upper()
                reclassified += 1

            # ── 2. Rejeitar ──
            reject_ok = [i for i in body.reject_ids if i in owned]
            not_found.extend(i for i in body.reject_ids if i not in owned)
            rejected = 0
            if reject_ok:
                result = await conn.execute(
                    """UPDATE kw_staging SET status = 'rejected', updated_at = NOW()
                        WHERE id = ANY($1::int[]) AND status <> 'rejected'""",
                    reject_ok,
                )
                rejected = int(result.split()[-1])

            # ── 3. Aprovar ──
            skipped_descarta = 0
            approved = 0
            if body.approve_all_non_descarta:
                result = await conn.execute(
                    f"""UPDATE kw_staging AS k
                           SET status = 'approved', updated_at = NOW()
                          FROM pesquisas p
                         WHERE k.pesquisa_id = p.id
                           AND {where_proj}
                           AND p.status = ANY($3::text[])
                           AND k.status = 'pending'
                           AND UPPER(COALESCE(k.kw_type, '')) <> 'DESCARTA'""",
                    *proj_params, list(PESQUISA_STATUS_REVISAVEL),
                )
                approved = int(result.split()[-1])
                skipped_descarta = await conn.fetchval(
                    f"""SELECT COUNT(*)
                          FROM kw_staging k
                          JOIN pesquisas p ON p.id = k.pesquisa_id
                         WHERE {where_proj}
                           AND k.status = 'pending'
                           AND UPPER(COALESCE(k.kw_type, '')) = 'DESCARTA'""",
                    *proj_params,
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
                    result = await conn.execute(
                        """UPDATE kw_staging SET status = 'approved', updated_at = NOW()
                            WHERE id = ANY($1::int[]) AND status <> 'approved'""",
                        aprovaveis,
                    )
                    approved = int(result.split()[-1])

            # ── 4. Subir status das pesquisas tocadas ──
            pesquisas_atualizadas: list[str] = []
            if body.aprovar_pesquisas and (approved or body.approve_all_non_descarta):
                rows = await conn.fetch(
                    f"""UPDATE pesquisas p
                           SET status = 'aprovado', reviewed_at = NOW()
                         WHERE {where_proj}
                           AND p.status = 'classificado'
                           AND EXISTS (
                                 SELECT 1 FROM kw_staging k
                                  WHERE k.pesquisa_id = p.id AND k.status = 'approved')
                     RETURNING p.id""",
                    *proj_params,
                )
                pesquisas_atualizadas = [str(r["id"]) for r in rows]

            # ── Saldo ──
            pending_restantes = await conn.fetchval(
                f"""SELECT COUNT(*)
                      FROM kw_staging k
                      JOIN pesquisas p ON p.id = k.pesquisa_id
                     WHERE {where_proj}
                       AND k.status = 'pending'
                       AND UPPER(COALESCE(k.kw_type, '')) <> 'DESCARTA'""",
                *proj_params,
            ) or 0

    return {
        "approved": approved,
        "rejected": rejected,
        "reclassified": reclassified,
        "skipped_descarta": int(skipped_descarta),
        "pending_restantes": int(pending_restantes),
        "pesquisas_atualizadas": pesquisas_atualizadas,
        "not_found": sorted(set(not_found)),
        "invalid": invalid,
    }


@router.post("/{projeto_id}/keywords/approve-classified")
async def approve_classified_keywords(projeto_id: str):
    """Bulk approve das kw_staging pending (kw_type != 'DESCARTA') do projeto.

    Mantido para compatibilidade com scripts/agentes que já chamavam o path.
    O caminho canônico do Board agora é `POST /projetos/{id}/keywords/approve`.

    Filtro: pesquisa vinculada ao projeto por UUID **ou** INT legado, com
    status IN ('classificado', 'aprovado'), kw_staging.status = 'pending' e
    UPPER(kw_type) != 'DESCARTA'.

    Idempotente: rerun encontra 0 rows em pending → approved=0.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await _resolve_projeto(conn, projeto_id)
            pid_int = proj["id_int_legado"]
            where_proj = _where_projeto(1, 2)
            params = [projeto_id, pid_int, list(PESQUISA_STATUS_REVISAVEL)]

            # Descobre pesquisas afetadas (antes do UPDATE — depois seriam approved)
            pesquisas_rows = await conn.fetch(
                f"""SELECT DISTINCT p.id
                      FROM pesquisas p
                      JOIN kw_staging k ON k.pesquisa_id = p.id
                     WHERE {where_proj}
                       AND p.status = ANY($3::text[])
                       AND k.status = 'pending'
                       AND UPPER(COALESCE(k.kw_type, '')) != 'DESCARTA'""",
                *params,
            )
            pesquisas_atualizadas = [str(r["id"]) for r in pesquisas_rows]

            # Conta DESCARTA pendentes (skipped)
            skipped = await conn.fetchval(
                f"""SELECT COUNT(*)
                      FROM kw_staging k
                      JOIN pesquisas p ON p.id = k.pesquisa_id
                     WHERE {where_proj}
                       AND p.status = ANY($3::text[])
                       AND k.status = 'pending'
                       AND UPPER(COALESCE(k.kw_type, '')) = 'DESCARTA'""",
                *params,
            )

            # UPDATE em massa — pré-existência do filtro garante idempotência
            result = await conn.execute(
                f"""UPDATE kw_staging AS k
                       SET status = 'approved', updated_at = NOW()
                      FROM pesquisas p
                     WHERE k.pesquisa_id = p.id
                       AND {where_proj}
                       AND p.status = ANY($3::text[])
                       AND k.status = 'pending'
                       AND UPPER(COALESCE(k.kw_type, '')) != 'DESCARTA'""",
                *params,
            )
            # asyncpg retorna "UPDATE N"
            approved = int(result.split()[-1])

    return {
        "approved": approved,
        "skipped_descarta": int(skipped or 0),
        "pesquisas_atualizadas": pesquisas_atualizadas,
    }
