"""
Endpoints de gestão de keywords — Phase 32.
NÃO adicionar Depends de auth: middleware global em main.py cuida disso (decisão D-09).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from db import get_pool

ALLOWED_KW_TYPES = {
    "PAGINA_PRINCIPAL", "PAGINA_GEO", "LOCALIDADE",
    "SECAO", "SURPRESA", "DESCARTA", "SERVICO"
}

router = APIRouter(prefix="/pesquisas", tags=["kw-mgmt"])


class ReclassifyItem(BaseModel):
    keyword_id: int
    kw_type: str


class BulkReclassifyRequest(BaseModel):
    items: list[ReclassifyItem] = Field(..., min_length=1, max_length=2000)


@router.patch("/{pesquisa_id}/keywords/bulk-reclassify")
async def bulk_reclassify(pesquisa_id: str, body: BulkReclassifyRequest):
    pool = await get_pool()
    invalid = []
    async with pool.acquire() as conn:
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pesquisas WHERE id = $1::uuid",
                pesquisa_id,
            )
        except Exception:
            raise HTTPException(422, "pesquisa_id não é um UUID válido")
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
        existing_rows = await conn.fetch(
            "SELECT id FROM kw_staging WHERE id = ANY($1::int[]) AND pesquisa_id = $2::uuid",
            ids,
            pesquisa_id,
        )
        existing_ids = {r["id"] for r in existing_rows}
        not_found = [i for i in ids if i not in existing_ids]
        to_update = [i for i in valid_items if i.keyword_id in existing_ids]

        updated = 0
        async with conn.transaction():
            for item in to_update:
                await conn.execute(
                    "UPDATE kw_staging SET kw_type = $1, updated_at = NOW() WHERE id = $2 AND pesquisa_id = $3::uuid",
                    item.kw_type,
                    item.keyword_id,
                    pesquisa_id,
                )
                updated += 1

    return {"updated": updated, "not_found": not_found, "invalid": invalid}
