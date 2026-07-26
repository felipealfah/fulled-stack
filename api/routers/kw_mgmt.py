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

PROJETO_STATUS_LIVE = ("deploy", "monetizacao", "manutencao")

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
