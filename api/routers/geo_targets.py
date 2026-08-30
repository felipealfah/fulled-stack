"""geo_targets.py — GET/POST/DELETE /projetos/{id}/geo-targets

Gerencia as regiões alvo (bairros, cidades, estados) associadas a um projeto.
Usado pelo competitive_intel agent e pelo frontend SeoPlan.tsx, que sempre manda
o UUID da rota.

## Fase 35 / D-02 — projeto_geo_targets mora no Supabase (schema `leadgen`)
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Os 3 handlers passam a ser de dois passos, sem uma linha de SQL alterada:

  1. `c_pg` (pool do Postgres da Stack) resolve o projeto via `_resolve_projeto_id_int`.
     Sem FK cross-DB esse passo deixa de ser conveniência e vira o **único** controle de
     acesso entre projetos (mitigação T-35-05) — o `projeto_id` do path nunca vai direto
     ao Supabase.
  2. `c_lg` (pool do Supabase, `db_leadgen.get_lg_pool`) executa TODO o SQL de
     `projeto_geo_targets`. O `search_path=leadgen` do pool resolve o schema, então as
     queries continuam dizendo `FROM projeto_geo_targets` sem prefixo.

O DELETE continua sendo soft (`ativo = false`), e continua escopado por `projeto_id`
no passo 1 + pelo `id` da região no passo 2 — a checagem de titularidade da região
segue dentro do mesmo banco, sem cruzar a fronteira.

## Correção junto: path param passa a ser UUID (str)
Igual ao que a Phase 12-02 fez em `content.py`. Este router declarava `projeto_id: int`
e ficou órfão da migração UUID da Phase 05 — medido em 2026-08-30 contra o código vivo:

    GET /projetos/{uuid}/geo-targets -> 422 (int_parsing)
    GET /projetos/8/geo-targets      -> 500 (DataError: int contra coluna uuid)

Ou seja: os 3 endpoints estavam quebrados para QUALQUER entrada. `projetos.id` é `uuid`
desde a migration 021; a tabela mantém `projeto_id` INTEGER (é `id_int_legado`), por
isso a resolução UUID → INT.

Segurança (T-35-06): parâmetros posicionais $1..$4 em todos os handlers — nunca f-string
com valor vindo do usuário.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool
from db_leadgen import get_lg_pool
from routers._common import _resolve_projeto_id_int

router = APIRouter(prefix="/projetos", tags=["geo-targets"])


class GeoTargetCreate(BaseModel):
    nome: str
    tipo: str | None = None   # 'bairro' | 'cidade' | 'estado'
    volume_estimado: int | None = None


@router.get("/{projeto_id}/geo-targets")
async def list_geo_targets(projeto_id: str):
    # Passo 1 — projeto resolvido no Postgres da Stack (camada de decisão).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        id_int = await _resolve_projeto_id_int(c_pg, projeto_id)

    # Fase 35 / D-02: projeto_geo_targets mora no Supabase (schema leadgen).
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        rows = await c_lg.fetch(
            """SELECT id, nome, tipo, volume_estimado, ativo, created_at
               FROM projeto_geo_targets
               WHERE projeto_id = $1 AND ativo = true
               ORDER BY created_at""",
            id_int,
        )
    return [dict(r) for r in rows]


@router.post("/{projeto_id}/geo-targets")
async def create_geo_target(projeto_id: str, body: GeoTargetCreate):
    if body.tipo and body.tipo not in ("bairro", "cidade", "estado"):
        raise HTTPException(400, "tipo deve ser 'bairro', 'cidade' ou 'estado'")

    # Passo 1 — projeto resolvido no Postgres da Stack (camada de decisão).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        id_int = await _resolve_projeto_id_int(c_pg, projeto_id)

    # Fase 35 / D-02: projeto_geo_targets mora no Supabase (schema leadgen).
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        new_row = await c_lg.fetchrow(
            """INSERT INTO projeto_geo_targets (projeto_id, nome, tipo, volume_estimado)
               VALUES ($1, $2, $3, $4)
               RETURNING id, nome, tipo, volume_estimado, ativo, created_at""",
            id_int, body.nome, body.tipo, body.volume_estimado,
        )
    return dict(new_row)


@router.delete("/{projeto_id}/geo-targets/{geo_id}")
async def delete_geo_target(projeto_id: str, geo_id: int):
    # Passo 1 — projeto resolvido no Postgres da Stack (camada de decisão).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        id_int = await _resolve_projeto_id_int(c_pg, projeto_id)

    # Fase 35 / D-02: projeto_geo_targets mora no Supabase (schema leadgen).
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        row = await c_lg.fetchrow(
            "SELECT id FROM projeto_geo_targets WHERE id = $1 AND projeto_id = $2",
            geo_id, id_int,
        )
        if not row:
            raise HTTPException(404, "Região alvo não encontrada")
        await c_lg.execute(
            "UPDATE projeto_geo_targets SET ativo = false WHERE id = $1",
            geo_id,
        )
    return {"status": "ok"}
