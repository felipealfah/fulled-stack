"""REQ-8-05 — PUT /projetos/{projeto_id}/competitor-audit.

Upsert em competitor_audits usando ON CONFLICT (projeto_id_uuid) DO UPDATE.
UNIQUE INDEX competitor_audits_projeto_uuid_key criado na migration 027 (plan 10-01).

Ainda popula projeto_id INT legado (NOT NULL) via projetos.id_int_legado.
Auth via middleware — decisão D-09.

Uso pelo agente `/competitor-audit` após scraping de top 3 concorrentes orgânicos.
"""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["competitor-audit"])


class MarketGaps(BaseModel):
    """Payload dos gaps de mercado — todos os campos do schema competitor_audits."""

    benchmark_word_count: int | None = None
    required_sections: list[str] = Field(default_factory=list)
    schema_missing: list[str] = Field(default_factory=list)
    geo_pages_benchmark: int = 0
    backlink_benchmark: int | None = None  # schema é INTEGER
    trust_gaps: list[str] = Field(default_factory=list)
    summary: str | None = None


class CompetitorAuditPayload(BaseModel):
    slug: str
    keyword_principal: str
    generated_at: str  # ISO 8601 — validado explicitamente para msg pt-BR
    competitors: list[dict]
    market_gaps: MarketGaps
    yaml_path: str | None = None


@router.put("/{projeto_id}/competitor-audit")
async def upsert_competitor_audit(projeto_id: str, body: CompetitorAuditPayload):
    """Upsert idempotente do competitor_audit do projeto.

    ON CONFLICT (projeto_id_uuid) DO UPDATE — retry produz mesmo estado no banco.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await _resolve_projeto(conn, projeto_id)
            pid_int = proj["id_int_legado"]
            pid_uuid = str(proj["id"])
            if pid_int is None:
                raise HTTPException(
                    500,
                    "Projeto sem id_int_legado — competitor_audits.projeto_id é NOT NULL",
                )

            try:
                generated_at = datetime.fromisoformat(body.generated_at)
            except ValueError:
                raise HTTPException(422, "generated_at deve ser ISO 8601")

            gaps = body.market_gaps
            row = await conn.fetchrow(
                """
                INSERT INTO competitor_audits
                    (projeto_id, projeto_id_uuid, slug, keyword_principal, generated_at,
                     competitor_count, benchmark_word_count, required_sections, schema_missing,
                     geo_pages_benchmark, backlink_benchmark, trust_gaps, summary,
                     competitors_json, yaml_path, created_at, updated_at)
                VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb,
                        $10, $11, $12::jsonb, $13, $14::jsonb, $15, NOW(), NOW())
                ON CONFLICT (projeto_id_uuid) DO UPDATE SET
                    projeto_id           = EXCLUDED.projeto_id,
                    slug                 = EXCLUDED.slug,
                    keyword_principal    = EXCLUDED.keyword_principal,
                    generated_at         = EXCLUDED.generated_at,
                    competitor_count     = EXCLUDED.competitor_count,
                    benchmark_word_count = EXCLUDED.benchmark_word_count,
                    required_sections    = EXCLUDED.required_sections,
                    schema_missing       = EXCLUDED.schema_missing,
                    geo_pages_benchmark  = EXCLUDED.geo_pages_benchmark,
                    backlink_benchmark   = EXCLUDED.backlink_benchmark,
                    trust_gaps           = EXCLUDED.trust_gaps,
                    summary              = EXCLUDED.summary,
                    competitors_json     = EXCLUDED.competitors_json,
                    yaml_path            = EXCLUDED.yaml_path,
                    updated_at           = NOW()
                RETURNING *
                """,
                pid_int,
                pid_uuid,
                body.slug,
                body.keyword_principal,
                generated_at,
                len(body.competitors),
                gaps.benchmark_word_count,
                json.dumps(gaps.required_sections),
                json.dumps(gaps.schema_missing),
                gaps.geo_pages_benchmark,
                gaps.backlink_benchmark,
                json.dumps(gaps.trust_gaps),
                gaps.summary,
                # default=str protege datetimes e outros non-JSON no dict do competitor
                json.dumps(body.competitors, default=str),
                body.yaml_path,
            )

    r = dict(row)

    # Parse defensivo dos jsonb — codec pode não estar ativo em RETURNING
    # dependendo do driver/pool. Sempre normaliza para list/dict Python.
    def _to_py(v, default):
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

    return {
        "slug": r["slug"],
        "keyword_principal": r["keyword_principal"],
        "generated_at": r["generated_at"].isoformat() if r["generated_at"] else None,
        "competitor_count": r["competitor_count"],
        "market_gaps": {
            "benchmark_word_count": r["benchmark_word_count"],
            "required_sections": _to_py(r["required_sections"], []),
            "schema_missing": _to_py(r["schema_missing"], []),
            "geo_pages_benchmark": r["geo_pages_benchmark"],
            "backlink_benchmark": r["backlink_benchmark"],
            "trust_gaps": _to_py(r["trust_gaps"], []),
            "summary": r["summary"],
        },
        "competitors": _to_py(r["competitors_json"], []),
        "yaml_path": r["yaml_path"],
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }
