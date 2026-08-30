"""
Endpoints de gestão de keywords — Phase 32.
NÃO adicionar Depends de auth: middleware global em main.py cuida disso (decisão D-09).

## Fase 35 / D-02 — `kw_staging` e as tabelas de scorecard moram no Supabase
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Este router atravessa a fronteira dos dois bancos:
  - `pesquisas` e `projetos` (camada de **decisão**) continuam no Postgres da Stack;
  - `kw_staging`, `kw_classification_overrides`, `scorecard_overrides` e `kw_scorecard`
    (camada **pré-decisão**) passaram para o schema `leadgen` no Supabase.

Consequência estrutural: não existe mais FK atravessando a fronteira. O que o banco
garantia — titularidade da keyword e limpeza em cascata — passa a ser responsabilidade
explícita destes handlers.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_pool
from db_leadgen import get_lg_pool

ALLOWED_KW_TYPES = {
    "PAGINA_PRINCIPAL", "PAGINA_GEO", "LOCALIDADE",
    "SECAO", "SURPRESA", "DESCARTA", "SERVICO"
}

PROJETO_STATUS_LIVE = ("deploy", "monetizacao", "manutencao")

router = APIRouter(prefix="/pesquisas", tags=["kw-mgmt"])

# Fase 35 / D-02: uma instrução para o lote inteiro (o contrato aceita até 2000 itens).
# O `AND kw_staging.pesquisa_id = $3::uuid` repete no próprio banco o filtro de
# titularidade que a FK garantia — é o que impede um `keyword_id` forjado no corpo
# atingir keyword de outra pesquisa (T-35-05). O `RETURNING` devolve exatamente os ids
# que casaram, dispensando o SELECT de descoberta que existia antes.
_SQL_BULK_RECLASSIFY = """
UPDATE kw_staging
   SET kw_type    = t.tipo,
       updated_at = NOW()
  FROM unnest($1::int[], $2::text[]) AS t(id, tipo)
 WHERE kw_staging.id = t.id
   AND kw_staging.pesquisa_id = $3::uuid
RETURNING kw_staging.id
"""


def _e_uuid_malformado(e: Exception) -> bool:
    """Distingue 'o path param não é UUID' de qualquer outra falha do banco.

    O `except Exception` genérico que existia aqui transformava *qualquer* erro — pool
    indisponível, timeout, permissão — num 422 'pesquisa_id não é um UUID válido',
    escondendo a causa real. Mesmo tratamento adotado em `intel.py` na Fase 35.
    """
    msg = str(e).lower()
    return "invalid input syntax" in msg or "uuid" in msg


class ReclassifyItem(BaseModel):
    keyword_id: int
    kw_type: str


class BulkReclassifyRequest(BaseModel):
    items: list[ReclassifyItem] = Field(..., min_length=1, max_length=2000)


@router.patch("/{pesquisa_id}/keywords/bulk-reclassify")
async def bulk_reclassify(pesquisa_id: str, body: BulkReclassifyRequest):
    """Reclassifica `kw_type` de um lote de keywords. Nunca 500 global.

    ## Fase 35 / D-02 — dois passos, um round-trip de escrita
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    1. `c_pg` (Postgres da Stack) confere a existência da pesquisa — `pesquisas` é camada
       de decisão e não migrou. Sem FK cross-DB este passo é o primeiro controle de
       titularidade (T-35-05); o `WHERE` do UPDATE o repete no outro banco.
    2. `c_lg` (Supabase) executa **uma única** instrução para o lote inteiro.

    O laço item a item que existia aqui emitia um `execute` por keyword. Com o banco em
    `localhost` era um round-trip local; depois do corte cada volta atravessa a internet,
    e o contrato aceita `max_length=2000` — seriam 2000 RTTs por request. Em lote o custo
    de rede é **constante** (Pitfall 8).
    """
    invalid = []

    # Fase 35 / D-02: passo 1 — `pesquisas` continua no Postgres da Stack.
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        try:
            exists = await c_pg.fetchval(
                "SELECT 1 FROM pesquisas WHERE id = $1::uuid",
                pesquisa_id,
            )
        except Exception as e:
            if _e_uuid_malformado(e):
                raise HTTPException(422, "pesquisa_id não é um UUID válido")
            raise
        if not exists:
            raise HTTPException(404, "Pesquisa não encontrada")

    valid_items = []
    for item in body.items:
        if item.kw_type not in ALLOWED_KW_TYPES:
            invalid.append({
                "id": item.keyword_id,
                "reason": f"kw_type inválido: '{item.kw_type}'. Aceitos: {sorted(ALLOWED_KW_TYPES)}",
            })
        else:
            valid_items.append(item)

    if not valid_items:
        return {"updated": 0, "not_found": [], "invalid": invalid}

    ids = [i.keyword_id for i in valid_items]

    # Deduplicação por keyword_id mantendo a ÚLTIMA ocorrência: é o estado que o laço
    # item a item deixava no banco (cada escrita sobrescrevia a anterior). Sem isso o
    # `unnest` daria duas linhas-fonte para a mesma linha-alvo e o Postgres escolheria
    # uma delas de forma não determinística.
    por_id = {i.keyword_id: i for i in valid_items}
    lote = list(por_id.values())

    # Fase 35 / D-02: passo 2 — uma ida à rede, qualquer que seja o tamanho do lote.
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        async with c_lg.transaction():
            rows = await c_lg.fetch(
                _SQL_BULK_RECLASSIFY,
                [i.keyword_id for i in lote],
                [i.kw_type for i in lote],
                pesquisa_id,
            )

    existentes = {r["id"] for r in rows}
    # Contagem idêntica à do laço anterior: um por item válido cuja linha existe na pesquisa.
    updated = sum(1 for i in valid_items if i.keyword_id in existentes)
    not_found = [i for i in ids if i not in existentes]

    return {"updated": updated, "not_found": not_found, "invalid": invalid}


@router.delete("/{pesquisa_id}")
async def delete_pesquisa(pesquisa_id: str, force: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """SELECT p.id, p.projeto_id_uuid, proj.status AS projeto_status,
                          (SELECT COUNT(*) FROM kw_staging WHERE pesquisa_id = p.id) AS kw_count
                   FROM pesquisas p
                   LEFT JOIN projetos proj ON proj.id = p.projeto_id_uuid
                   WHERE p.id = $1::uuid""",
                pesquisa_id,
            )
        except Exception:
            raise HTTPException(422, "pesquisa_id não é um UUID válido")

        if not row:
            raise HTTPException(404, "Pesquisa não encontrada")

        if row["projeto_status"] in PROJETO_STATUS_LIVE and not force:
            raise HTTPException(
                409,
                "Pesquisa pertence a projeto em produção (status=" + row["projeto_status"] + ") — passe ?force=true para forçar",
            )

        deleted_keywords = row["kw_count"]

        async with conn.transaction():
            await conn.execute("DELETE FROM kw_classification_overrides WHERE pesquisa_id = $1::uuid", pesquisa_id)
            await conn.execute("DELETE FROM scorecard_overrides WHERE pesquisa_id = $1::uuid", pesquisa_id)
            await conn.execute("DELETE FROM kw_scorecard WHERE pesquisa_id = $1::uuid", pesquisa_id)
            await conn.execute("DELETE FROM agent_executions WHERE pesquisa_id = $1::uuid", pesquisa_id)
            await conn.execute(
                "UPDATE projetos SET pesquisa_id_atual = NULL WHERE pesquisa_id_atual = $1::uuid",
                pesquisa_id,
            )
            await conn.execute("DELETE FROM pesquisas WHERE id = $1::uuid", pesquisa_id)

    return {"deleted_keywords": deleted_keywords, "soft": False}
