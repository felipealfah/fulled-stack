"""REQ-8-06 — PUT /projetos/{projeto_id}/backlink-intel.

Upsert em backlink_intel (tabela criada na migration 028 do plan 10-01).
PK natural: projeto_id UUID. ON CONFLICT (projeto_id) DO UPDATE.

Auth via middleware — decisão D-09.

Uso pelo agente `/backlink-intel` após scraping do Apify Backlinks Checker.
"""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["backlink-intel"])


class BacklinkSummary(BaseModel):
    avg_competitor_dofollow_backlinks: float | None = None
    total_opportunities: int = 0
    high_priority_count: int = 0
    recommended_strategy: str | None = None


class BacklinkIntelPayload(BaseModel):
    slug: str
    keyword_principal: str
    generated_at: str  # ISO 8601
    summary: BacklinkSummary
    competitors_analyzed: list[dict]
    opportunities: list[dict]


def _to_py(v, default):
    """Parse defensivo do jsonb no RETURNING — codec pode não estar ativo."""
    if v is None:
        return default
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return default
    return default


@router.put("/{projeto_id}/backlink-intel")
async def upsert_backlink_intel(projeto_id: str, body: BacklinkIntelPayload):
    """Upsert idempotente do backlink_intel do projeto.

    ON CONFLICT (projeto_id) DO UPDATE — retry produz mesmo estado no banco.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await _resolve_projeto(conn, projeto_id)
            pid_uuid = str(proj["id"])

            try:
                generated_at = datetime.fromisoformat(body.generated_at)
            except ValueError:
                raise HTTPException(422, "generated_at deve ser ISO 8601")

            row = await conn.fetchrow(
                """
                INSERT INTO backlink_intel
                    (projeto_id, slug, keyword_principal, generated_at,
                     summary, competitors_analyzed, opportunities,
                     created_at, updated_at)
                VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, NOW(), NOW())
                ON CONFLICT (projeto_id) DO UPDATE SET
                    slug                 = EXCLUDED.slug,
                    keyword_principal    = EXCLUDED.keyword_principal,
                    generated_at         = EXCLUDED.generated_at,
                    summary              = EXCLUDED.summary,
                    competitors_analyzed = EXCLUDED.competitors_analyzed,
                    opportunities        = EXCLUDED.opportunities,
                    updated_at           = NOW()
                RETURNING *
                """,
                pid_uuid,
                body.slug,
                body.keyword_principal,
                generated_at,
                json.dumps(body.summary.model_dump()),
                json.dumps(body.competitors_analyzed, default=str),
                json.dumps(body.opportunities, default=str),
            )

    r = dict(row)
    return {
        "projeto_id": str(r["projeto_id"]),
        "slug": r["slug"],
        "keyword_principal": r["keyword_principal"],
        "generated_at": r["generated_at"].isoformat() if r["generated_at"] else None,
        "summary": _to_py(r["summary"], {}),
        "competitors_analyzed": _to_py(r["competitors_analyzed"], []),
        "opportunities": _to_py(r["opportunities"], []),
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }
