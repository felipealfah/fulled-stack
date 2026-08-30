"""overrides.py — GET/POST/DELETE /projetos/{id}/ranking/overrides

Promoções e bloqueios manuais de keyword no rank_intel, por projeto.
Consumido por `ProjetoRanking.tsx` (frontend), que sempre manda o UUID da rota.

## Fase 35 / D-02 — rank_intel_overrides mora no Supabase (schema `leadgen`)
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Os 3 handlers passam a ser de dois passos, sem uma linha de SQL alterada:

  1. `c_pg` (pool do Postgres da Stack) resolve o projeto via `_resolve_projeto_id_int`.
     Sem FK cross-DB esse passo deixa de ser conveniência e vira o **único** controle de
     acesso entre projetos (mitigação T-35-05) — o `projeto_id` do path nunca vai direto
     ao Supabase. `list_overrides` não fazia essa resolução; agora faz.
  2. `c_lg` (pool do Supabase, `db_leadgen.get_lg_pool`) executa TODO o SQL de
     `rank_intel_overrides`. O `search_path=leadgen` do pool resolve o schema, então as
     queries continuam dizendo `FROM rank_intel_overrides` sem prefixo.

## Correção junto: path param passa a ser UUID (str)
Igual ao que a Phase 12-02 fez em `content.py`. Este router declarava `projeto_id: int`
e ficou órfão da migração UUID da Phase 05 — medido em 2026-08-30 contra o código vivo:

    GET /projetos/{uuid}/ranking/overrides -> 422 (int_parsing)
    GET /projetos/8/ranking/overrides      -> 200  (nenhum cliente manda int)

`projetos.id` é `uuid` desde a migration 021, então o `SELECT id FROM projetos WHERE
id = $1` do POST comparava INT com UUID e levantava `DataError` → 500. A tabela mantém
`projeto_id` INTEGER (é `id_int_legado`), por isso a resolução UUID → INT.

Segurança (T-35-06): parâmetros posicionais $1..$4 em todos os handlers — nunca f-string
com valor vindo do usuário.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool
from db_leadgen import get_lg_pool
from routers._common import _resolve_projeto_id_int

router = APIRouter(prefix="/projetos", tags=["overrides"])


class OverrideCreate(BaseModel):
    keyword: str
    action: str  # 'promote' | 'block'
    kw_type: str | None = None


@router.get("/{projeto_id}/ranking/overrides")
async def list_overrides(projeto_id: str):
    # Passo 1 — projeto resolvido no Postgres da Stack (camada de decisão).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        id_int = await _resolve_projeto_id_int(c_pg, projeto_id)

    # Fase 35 / D-02: rank_intel_overrides mora no Supabase (schema leadgen).
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        rows = await c_lg.fetch(
            "SELECT id, keyword, action, kw_type, created_at FROM rank_intel_overrides WHERE projeto_id = $1 ORDER BY created_at DESC",
            id_int,
        )
    return [dict(r) for r in rows]


@router.post("/{projeto_id}/ranking/overrides")
async def upsert_override(projeto_id: str, body: OverrideCreate):
    if body.action not in ("promote", "block"):
        raise HTTPException(400, "action deve ser 'promote' ou 'block'")
    if body.action == "promote" and not body.kw_type:
        raise HTTPException(400, "kw_type obrigatório para action='promote'")

    # Passo 1 — projeto resolvido no Postgres da Stack (camada de decisão).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        id_int = await _resolve_projeto_id_int(c_pg, projeto_id)

    # Fase 35 / D-02: rank_intel_overrides mora no Supabase (schema leadgen).
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        await c_lg.execute("""
            INSERT INTO rank_intel_overrides (projeto_id, keyword, action, kw_type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (projeto_id, keyword) DO UPDATE
              SET action = EXCLUDED.action, kw_type = EXCLUDED.kw_type, created_at = NOW()
        """, id_int, body.keyword, body.action, body.kw_type)

    return {"status": "ok"}


@router.delete("/{projeto_id}/ranking/overrides/{keyword}")
async def delete_override(projeto_id: str, keyword: str):
    # Passo 1 — projeto resolvido no Postgres da Stack (camada de decisão).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        id_int = await _resolve_projeto_id_int(c_pg, projeto_id)

    # Fase 35 / D-02: rank_intel_overrides mora no Supabase (schema leadgen).
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        result = await c_lg.execute(
            "DELETE FROM rank_intel_overrides WHERE projeto_id = $1 AND keyword = $2",
            id_int, keyword,
        )
    deleted = int(result.split()[-1])
    if deleted == 0:
        raise HTTPException(404, "Override não encontrado")
    return {"status": "ok"}
