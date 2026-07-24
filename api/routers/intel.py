"""REQ-8-04 — PATCH /pesquisas/{pesquisa_id}/keywords/bulk-intel.

Bulk UPDATE em kw_staging com error accumulation.
NUNCA retorna 500 global — sempre 200 com {updated, not_found, invalid}.

Vocabulário difficulty_label canônico (D-04): 'LOW', 'MED', 'HIGH' (uppercase ASCII).
Auth via middleware HTTP — decisão D-09.
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool

router = APIRouter(prefix="/pesquisas", tags=["intel"])

CANONICAL_DIFFICULTY = {"LOW", "MED", "HIGH"}


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
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pesquisas WHERE id = $1::uuid", pesquisa_id
            )
        except Exception as e:
            msg = str(e).lower()
            if "invalid input syntax" in msg or "uuid" in msg:
                raise HTTPException(422, "pesquisa_id não é um UUID válido")
            raise
        if not exists:
            raise HTTPException(404, "Pesquisa não encontrada")

        updated = 0
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

        # Descobrir quais IDs existem na pesquisa
        ids = [i.keyword_id for i in valid_items]
        existing_rows = await conn.fetch(
            "SELECT id FROM kw_staging WHERE id = ANY($1::int[]) AND pesquisa_id = $2::uuid",
            ids, pesquisa_id,
        )
        existing_ids = {r["id"] for r in existing_rows}
        not_found = [i for i in ids if i not in existing_ids]
        to_update = [i for i in valid_items if i.keyword_id in existing_ids]

        async with conn.transaction():
            for item in to_update:
                await conn.execute(
                    """UPDATE kw_staging
                          SET competitive_score  = $2,
                              difficulty_label   = $3,
                              top_competitor_url = $4,
                              intel_json         = $5::jsonb,
                              intel_updated_at   = NOW(),
                              updated_at         = NOW()
                        WHERE id = $1""",
                    item.keyword_id,
                    item.competitive_score,
                    item.difficulty_label,
                    item.top_competitor_url,
                    json.dumps(item.intel_json),
                )
                updated += 1

    return {"updated": updated, "not_found": not_found, "invalid": invalid}
