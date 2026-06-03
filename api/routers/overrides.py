"""overrides.py — GET/POST/DELETE /projetos/{id}/ranking/overrides"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool

router = APIRouter(prefix="/projetos", tags=["overrides"])


class OverrideCreate(BaseModel):
    keyword: str
    action: str  # 'promote' | 'block'
    kw_type: str | None = None


@router.get("/{projeto_id}/ranking/overrides")
async def list_overrides(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, keyword, action, kw_type, created_at FROM rank_intel_overrides WHERE projeto_id = $1 ORDER BY created_at DESC",
            projeto_id,
        )
    return [dict(r) for r in rows]


@router.post("/{projeto_id}/ranking/overrides")
async def upsert_override(projeto_id: int, body: OverrideCreate):
    if body.action not in ("promote", "block"):
        raise HTTPException(400, "action deve ser 'promote' ou 'block'")
    if body.action == "promote" and not body.kw_type:
        raise HTTPException(400, "kw_type obrigatório para action='promote'")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        await conn.execute("""
            INSERT INTO rank_intel_overrides (projeto_id, keyword, action, kw_type)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (projeto_id, keyword) DO UPDATE
              SET action = EXCLUDED.action, kw_type = EXCLUDED.kw_type, created_at = NOW()
        """, projeto_id, body.keyword, body.action, body.kw_type)

    return {"status": "ok"}


@router.delete("/{projeto_id}/ranking/overrides/{keyword}")
async def delete_override(projeto_id: int, keyword: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM rank_intel_overrides WHERE projeto_id = $1 AND keyword = $2",
            projeto_id, keyword,
        )
    deleted = int(result.split()[-1])
    if deleted == 0:
        raise HTTPException(404, "Override não encontrado")
    return {"status": "ok"}
