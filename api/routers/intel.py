"""REQ-8-04 — PATCH /pesquisas/{pesquisa_id}/keywords/bulk-intel.

Bulk UPDATE em kw_staging com error accumulation.
NUNCA retorna 500 global — sempre 200 com {updated, not_found, invalid}.

Vocabulário difficulty_label canônico (D-04): 'LOW', 'MED', 'HIGH' (uppercase ASCII).
Auth via middleware HTTP — decisão D-09.

## Fase 35 / D-02 — kw_staging mora no Supabase (schema `leadgen`)
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Handler de dois passos:
  1. `c_pg` (Postgres da Stack) confere a existência da pesquisa. `pesquisas` é camada de
     decisão e não migra. Sem FK cross-DB este passo é o único controle que impede escrever
     em keyword de outra pesquisa (T-35-05) — por isso ele vem primeiro, e o filtro
     `AND kw_staging.pesquisa_id = $6::uuid` do UPDATE o repete no próprio banco.
  2. `c_lg` (Supabase) executa **uma única** instrução de UPDATE para o lote inteiro.

### Por que o laço item a item virou UPDATE ... FROM unnest(...)
Antes o handler fazia um `conn.execute` por item, mais um `SELECT` de descoberta: com o
banco em `localhost` era um round-trip local por keyword. Depois do corte cada volta
atravessa a internet até o Supabase, e o contrato aceita lotes grandes — 2000 itens
custariam 2000 RTTs. A instrução em lote deixa o custo de rede **constante** (1 round-trip
para qualquer tamanho de lote), e o `RETURNING` devolve exatamente os ids que casaram,
dispensando também o SELECT de descoberta que existia antes.

Segurança (T-35-06): os cinco arrays entram como parâmetros posicionais tipados
(`$1::int[]` … `$5::jsonb[]`). Nenhum valor é concatenado na string do SQL.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool
from db_leadgen import get_lg_pool

router = APIRouter(prefix="/pesquisas", tags=["intel"])

CANONICAL_DIFFICULTY = {"LOW", "MED", "HIGH"}

# Fase 35 / D-02: uma instrução para o lote inteiro. O WHERE repete o filtro por
# pesquisa_id — é o que impede um id forjado no corpo atingir keyword de outra pesquisa
# agora que a FK não existe mais (T-35-05).
_SQL_BULK_UPDATE = """
UPDATE kw_staging
   SET competitive_score  = t.score,
       difficulty_label   = t.label,
       top_competitor_url = t.url,
       intel_json         = t.intel,
       intel_updated_at   = NOW(),
       updated_at         = NOW()
  FROM unnest($1::int[], $2::float8[], $3::text[], $4::text[], $5::jsonb[])
       AS t(id, score, label, url, intel)
 WHERE kw_staging.id = t.id
   AND kw_staging.pesquisa_id = $6::uuid
RETURNING kw_staging.id
"""


class KeywordIntelItem(BaseModel):
    keyword_id: int
    competitive_score: float
    difficulty_label: str  # validado inline para error accumulation, não via Enum
    top_competitor_url: str | None = None
    intel_json: dict


class BulkIntelRequest(BaseModel):
    items: list[KeywordIntelItem]


@router.patch("/{pesquisa_id}/keywords/bulk-intel")
async def bulk_update_intel(pesquisa_id: str, body: BulkIntelRequest):
    """Bulk UPDATE de intel em kw_staging com error accumulation.

    - Nunca retorna 500 global (CRIT-8).
    - difficulty_label deve ser LOW/MED/HIGH (D-04) — outros vão para invalid[].
    - competitive_score deve estar entre 0 e 100 — fora da faixa vai para invalid[].
    - keyword_ids inexistentes na pesquisa vão para not_found[].
    """
    # Fase 35 / D-02: passo 1 — `pesquisas` continua no Postgres da Stack.
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        try:
            exists = await c_pg.fetchval(
                "SELECT 1 FROM pesquisas WHERE id = $1::uuid", pesquisa_id
            )
        except Exception as e:
            msg = str(e).lower()
            if "invalid input syntax" in msg or "uuid" in msg:
                raise HTTPException(422, "pesquisa_id não é um UUID válido")
            raise
        if not exists:
            raise HTTPException(404, "Pesquisa não encontrada")

    not_found: list[int] = []
    invalid: list[dict] = []
    valid_items: list[KeywordIntelItem] = []

    # Validação inline (não usar Enum — permite error accumulation)
    for item in body.items:
        if item.difficulty_label not in CANONICAL_DIFFICULTY:
            invalid.append({
                "id": item.keyword_id,
                "reason": f"difficulty_label inválido: '{item.difficulty_label}'. Aceitos: LOW, MED, HIGH.",
            })
            continue
        if not (0 <= item.competitive_score <= 100):
            invalid.append({
                "id": item.keyword_id,
                "reason": "competitive_score deve estar entre 0 e 100",
            })
            continue
        valid_items.append(item)

    if not valid_items:
        return {"updated": 0, "not_found": [], "invalid": invalid}

    ids = [i.keyword_id for i in valid_items]

    # Deduplicação por keyword_id mantendo a ÚLTIMA ocorrência: é o estado que o laço
    # item a item deixava no banco (cada escrita sobrescrevia a anterior). Sem isso o
    # `unnest` daria duas linhas-fonte para a mesma linha-alvo e o Postgres escolheria
    # uma delas de forma não determinística.
    por_id: dict[int, KeywordIntelItem] = {i.keyword_id: i for i in valid_items}
    lote = list(por_id.values())

    # Fase 35 / D-02: passo 2 — uma única ida à rede, qualquer que seja o tamanho do lote.
    lg = await get_lg_pool()
    async with lg.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                _SQL_BULK_UPDATE,
                [i.keyword_id for i in lote],
                [i.competitive_score for i in lote],
                [i.difficulty_label for i in lote],
                [i.top_competitor_url for i in lote],
                # `intel_json` vai como dict: o codec JSONB de db_leadgen.py já aplica
                # json.dumps. Passar a string pré-serializada dava dupla codificação e
                # gravava um *texto* JSON (jsonb_typeof = 'string') em vez do objeto —
                # divergindo de todo outro escritor da tabela.
                [i.intel_json for i in lote],
                pesquisa_id,
            )

    existentes = {r["id"] for r in rows}
    # Contagem idêntica ao laço anterior: um por item válido cuja linha existe na pesquisa.
    updated = sum(1 for i in valid_items if i.keyword_id in existentes)
    not_found = [i for i in ids if i not in existentes]

    return {"updated": updated, "not_found": not_found, "invalid": invalid}
