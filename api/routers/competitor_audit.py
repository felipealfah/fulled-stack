"""REQ-8-05 — PUT /projetos/{projeto_id}/competitor-audit.

Upsert em competitor_audits usando ON CONFLICT (projeto_id_uuid) DO UPDATE.
UNIQUE INDEX competitor_audits_projeto_uuid_key criado na migration 027 (plan 10-01).

Ainda popula projeto_id INT legado (NOT NULL) via projetos.id_int_legado.
Auth via middleware — decisão D-09.

Uso pelo agente `/competitor-audit` após scraping de top 3 concorrentes orgânicos.

## Fase 35 / D-02 — competitor_audits mora no Supabase (schema `leadgen`)
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Handler de dois passos, sem uma linha de SQL alterada:
  1. `c_pg` (pool do Postgres da Stack) resolve o projeto em `projetos`. Sem FK cross-DB
     esse passo é o **único** controle de acesso entre projetos (mitigação T-35-05).
  2. `c_lg` (pool do Supabase) executa o upsert. O `search_path=leadgen` resolve o schema,
     então o SQL continua dizendo `INTO competitor_audits` sem prefixo.

A transação passou do pool do Postgres para o do Supabase: é lá que a escrita acontece, e
uma transação aberta no banco que só faz um SELECT não protege nada.

⚠️ `backlink_benchmark` NÃO existe em banco nenhum (nem na origem, nem no Supabase) — o
INSERT abaixo a referencia desde a Phase 10 e por isso este endpoint responde **500** em
produção. A migration 034 (Stack) + 20260830120000 (Supabase) criam a coluna; enquanto não
forem aplicadas, este handler continua quebrado. Ver 35-04-SUMMARY.md § Ação do Board.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_pool
from db_leadgen import get_lg_pool
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
    # Fase 35 / D-02: passo 1 — o projeto é resolvido no Postgres da Stack (camada de
    # decisão). É o controle que impede o `projeto_id` do path chegar cru ao Supabase.
    # O pool do Supabase só é aberto DEPOIS: 404/422/500 de projeto continuam corretos
    # mesmo com o Supabase fora do ar, e a ordem fica demonstrável (T-35-05).
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        proj = await _resolve_projeto(c_pg, projeto_id)
    pid_int = proj["id_int_legado"]
    pid_uuid = str(proj["id"])
    if pid_int is None:
        raise HTTPException(
            500,
            "Projeto sem id_int_legado — competitor_audits.projeto_id é NOT NULL",
        )

    try:
        # `Z` sufixo virou compatível com fromisoformat em 3.11+, mas normalizamos
        # para robustez com clientes que mandem "2026-07-24T18:00:00Z"
        generated_at = datetime.fromisoformat(body.generated_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "generated_at deve ser ISO 8601")

    # Coluna competitor_audits.generated_at é TIMESTAMP (sem TZ).
    # asyncpg falha ao encodar datetime aware contra TIMESTAMP — remover tz
    # (assumido UTC pelo cliente que padroniza ISO 8601 com Z ou offset explícito).
    if generated_at.tzinfo is not None:
        generated_at = generated_at.astimezone(timezone.utc).replace(tzinfo=None)

    # Fase 35 / D-02: passo 2 — todo o SQL de `competitor_audits` roda no Supabase.
    lg = await get_lg_pool()
    async with lg.acquire() as conn:
        async with conn.transaction():
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
