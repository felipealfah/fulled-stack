"""geo_targets.py — GET/POST/DELETE /projetos/{id}/geo-targets

Gerencia as regiões alvo (bairros, cidades, estados) associadas a um projeto.
Usado pelo competitive_intel agent e pelo frontend SeoPlan.tsx.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool

router = APIRouter(prefix="/projetos", tags=["geo-targets"])


class GeoTargetCreate(BaseModel):
    nome: str
    tipo: str | None = None   # 'bairro' | 'cidade' | 'estado'
    volume_estimado: int | None = None


@router.get("/{projeto_id}/geo-targets")
async def list_geo_targets(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not row:
            raise HTTPException(404, "Projeto não encontrado")
        rows = await conn.fetch(
            """SELECT id, nome, tipo, volume_estimado, ativo, created_at
               FROM projeto_geo_targets
               WHERE projeto_id = $1 AND ativo = true
               ORDER BY created_at""",
            projeto_id,
        )
    return [dict(r) for r in rows]


@router.post("/{projeto_id}/geo-targets")
async def create_geo_target(projeto_id: int, body: GeoTargetCreate):
    if body.tipo and body.tipo not in ("bairro", "cidade", "estado"):
        raise HTTPException(400, "tipo deve ser 'bairro', 'cidade' ou 'estado'")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        new_row = await conn.fetchrow(
            """INSERT INTO projeto_geo_targets (projeto_id, nome, tipo, volume_estimado)
               VALUES ($1, $2, $3, $4)
               RETURNING id, nome, tipo, volume_estimado, ativo, created_at""",
            projeto_id, body.nome, body.tipo, body.volume_estimado,
        )
    return dict(new_row)


@router.delete("/{projeto_id}/geo-targets/{geo_id}")
async def delete_geo_target(projeto_id: int, geo_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM projeto_geo_targets WHERE id = $1 AND projeto_id = $2",
            geo_id, projeto_id,
        )
        if not row:
            raise HTTPException(404, "Região alvo não encontrada")
        await conn.execute(
            "UPDATE projeto_geo_targets SET ativo = false WHERE id = $1",
            geo_id,
        )
    return {"status": "ok"}
