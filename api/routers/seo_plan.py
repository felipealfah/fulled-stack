"""seo_plan.py — Plano SEO por projeto

4 endpoints:
  GET    /projetos/{projeto_id}/seo-plan              — retorna plano + pages + keywords dropdown
  POST   /projetos/{projeto_id}/seo-plan/generate     — cria/regenera plano (ON CONFLICT DO NOTHING preserva kw_principal_id)
  PATCH  /projetos/{projeto_id}/seo-plan/pages/{id}   — atualiza kw_principal_id e/ou papel
  PATCH  /projetos/{projeto_id}/seo-plan/ready        — marca pronto + INSERT competitive_intel idempotente

Segurança (T-14-01): PATCH pages valida que page pertence ao projeto via JOIN.
Idempotência (T-14-02): /ready faz SELECT antes de INSERT em agent_executions.
SQL injection (T-14-03): f-string apenas para nomes de colunas (controlados pelo BaseModel).

Phase 05: projeto_id no path é UUID (str). Queries em tabelas legadas usam id_int_legado.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool

router = APIRouter(prefix="/projetos", tags=["seo-plan"])


async def _resolve_projeto(conn, projeto_id: str) -> dict:
    """Resolve UUID para linha do projeto com id_int_legado."""
    proj = await conn.fetchrow(
        "SELECT id, id_int_legado FROM projetos WHERE id = $1::uuid",
        projeto_id,
    )
    if not proj:
        raise HTTPException(404, "Projeto não encontrado")
    return dict(proj)


# ---------------------------------------------------------------------------
# GET /{projeto_id}/seo-plan
# ---------------------------------------------------------------------------

@router.get("/{projeto_id}/seo-plan")
async def get_seo_plan(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]

        plan_row = await conn.fetchrow(
            "SELECT * FROM projeto_seo_plan WHERE projeto_id = $1", pid_int
        )
        if not plan_row:
            raise HTTPException(404, "Plano SEO não encontrado")

        plan = dict(plan_row)

        pages_rows = await conn.fetch(
            """
            SELECT
              p.id,
              p.plan_id,
              p.pesquisa_id::text AS pesquisa_id,
              p.kw_principal_id,
              p.papel,
              p.created_at,
              p.competitive_score,
              p.difficulty_label,
              p.top_competitor_url,
              p.intel_updated_at,
              pes.nicho           AS pesquisa_nome,
              pes.status          AS pesquisa_status,
              kw.keyword          AS kw_principal_text,
              kw.avg_monthly_searches AS kw_principal_volume,
              latest_intel.intel_data
            FROM projeto_seo_plan_pages p
            LEFT JOIN pesquisas pes ON pes.id = p.pesquisa_id
            LEFT JOIN kw_staging kw ON kw.id = p.kw_principal_id
            LEFT JOIN LATERAL (
              SELECT intel_data FROM projeto_seo_plan_pages_intel pi
              WHERE pi.page_id = p.id ORDER BY pi.created_at DESC LIMIT 1
            ) latest_intel ON true
            WHERE p.plan_id = $1
              AND p.pesquisa_id IS NOT NULL
            ORDER BY p.created_at
            """,
            plan["id"],
        )

        pages = []
        for page_row in pages_rows:
            page = dict(page_row)
            kws = await conn.fetch(
                """
                SELECT id, keyword, avg_monthly_searches
                FROM kw_staging
                WHERE pesquisa_id = $1::uuid AND status = 'approved'
                ORDER BY avg_monthly_searches DESC NULLS LAST
                """,
                page["pesquisa_id"],
            )
            page["keywords"] = [dict(k) for k in kws]
            pages.append(page)

        sem_plano = await conn.fetch(
            """
            SELECT id::text FROM pesquisas
            WHERE projeto_id = $1
              AND status = 'gate_2_approved'
              AND id NOT IN (
                SELECT pesquisa_id FROM projeto_seo_plan_pages
                WHERE plan_id = $2 AND pesquisa_id IS NOT NULL
              )
            """,
            pid_int,
            plan["id"],
        )

        exec_row = await conn.fetchrow(
            """SELECT id FROM agent_executions
               WHERE projeto_id = $1
                 AND agent_name = 'competitive_intel'
                 AND status IN ('pending', 'in_progress')""",
            pid_int,
        )

        plan["pages"] = pages
        plan["pesquisas_sem_plano"] = [r["id"] for r in sem_plano]
        plan["competitive_intel_pending"] = exec_row is not None
        return plan


# ---------------------------------------------------------------------------
# POST /{projeto_id}/seo-plan/generate
# ---------------------------------------------------------------------------

@router.post("/{projeto_id}/seo-plan/generate")
async def generate_seo_plan(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]

        pesquisas = await conn.fetch(
            """SELECT id::text, papel FROM pesquisas
               WHERE projeto_id = $1 AND status IN ('gate_2_approved', 'aprovado')
               ORDER BY created_at""",
            pid_int,
        )

        plan_row = await conn.fetchrow(
            "SELECT id FROM projeto_seo_plan WHERE projeto_id = $1", pid_int
        )
        if plan_row:
            plan_id = plan_row["id"]
            await conn.execute(
                "UPDATE projeto_seo_plan SET updated_at = NOW() WHERE id = $1", plan_id
            )
        else:
            plan_id = await conn.fetchval(
                """INSERT INTO projeto_seo_plan (projeto_id, status)
                   VALUES ($1, 'rascunho') RETURNING id""",
                pid_int,
            )

        for p in pesquisas:
            await conn.execute(
                """INSERT INTO projeto_seo_plan_pages (plan_id, pesquisa_id, papel)
                   VALUES ($1, $2::uuid, $3)
                   ON CONFLICT (plan_id, pesquisa_id) DO NOTHING""",
                plan_id,
                p["id"],
                p["papel"],
            )

    return await get_seo_plan(projeto_id)


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/seo-plan/pages/{page_id}
# ---------------------------------------------------------------------------

class SeoPlanPageUpdate(BaseModel):
    kw_principal_id: int | None = None
    papel: Literal['principal', 'servico'] | None = None


@router.patch("/{projeto_id}/seo-plan/pages/{page_id}")
async def update_seo_plan_page(projeto_id: str, page_id: int, body: SeoPlanPageUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]

        # T-14-01: Validar que page pertence ao projeto (evitar PATCH cross-projeto)
        row = await conn.fetchrow(
            """SELECT p.id FROM projeto_seo_plan_pages p
               JOIN projeto_seo_plan sp ON sp.id = p.plan_id
               WHERE p.id = $1 AND sp.projeto_id = $2""",
            page_id,
            pid_int,
        )
        if not row:
            raise HTTPException(404, "Página do plano não encontrada")

        fields = body.model_dump(exclude_unset=True)
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        # T-14-03: f-string apenas para nomes de colunas (controlados pelo BaseModel)
        set_parts = []
        values = [page_id]
        for i, (k, v) in enumerate(fields.items(), start=2):
            set_parts.append(f"{k} = ${i}")
            values.append(v)

        set_clause = ", ".join(set_parts)
        await conn.execute(
            f"UPDATE projeto_seo_plan_pages SET {set_clause} WHERE id = $1",
            *values,
        )

        await conn.execute(
            """UPDATE projeto_seo_plan SET updated_at = NOW()
               WHERE id = (SELECT plan_id FROM projeto_seo_plan_pages WHERE id = $1)""",
            page_id,
        )

    return {"ok": True}


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/seo-plan/ready
# ---------------------------------------------------------------------------

@router.patch("/{projeto_id}/seo-plan/ready")
async def mark_seo_plan_ready(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]

        plan_row = await conn.fetchrow(
            "SELECT id FROM projeto_seo_plan WHERE projeto_id = $1", pid_int
        )
        if not plan_row:
            raise HTTPException(404, "Plano SEO não encontrado")

        await conn.execute(
            "UPDATE projeto_seo_plan SET status = 'pronto', updated_at = NOW() WHERE projeto_id = $1",
            pid_int,
        )

        # T-14-02: Idempotente — verificar antes de inserir
        existing = await conn.fetchrow(
            """SELECT id FROM agent_executions
               WHERE projeto_id = $1
                 AND agent_name = 'competitive_intel'
                 AND status IN ('pending', 'in_progress')""",
            pid_int,
        )

        exec_id = None
        if not existing:
            pesquisa_row = await conn.fetchrow(
                """SELECT id FROM pesquisas
                   WHERE projeto_id = $1 AND status = 'gate_2_approved'
                   ORDER BY created_at LIMIT 1""",
                pid_int,
            )
            if not pesquisa_row:
                print(f"[seo_plan] sem pesquisas gate_2_approved para projeto_id={pid_int}, competitive_intel não enfileirado", flush=True)
                return {"ok": True, "agent_executions_id": None}

            exec_id = await conn.fetchval(
                """INSERT INTO agent_executions
                   (projeto_id, pesquisa_id, analysis_version, agent_name, status, started_at)
                   VALUES ($1, $2, 1, 'competitive_intel', 'pending', NOW())
                   RETURNING id""",
                pid_int,
                pesquisa_row["id"],
            )
            print(f"[seo_plan] competitive_intel enfileirado para projeto_id={pid_int}", flush=True)
        else:
            exec_id = existing["id"]
            print(f"[seo_plan] competitive_intel já em fila para projeto_id={pid_int}, ignorando", flush=True)

    return {"ok": True, "agent_executions_id": exec_id}


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/seo-plan/pages/{page_id}/intel
# Phase 15 — Competitive Intel Agent
# ---------------------------------------------------------------------------


class SeoPlanPageIntelUpdate(BaseModel):
    competitive_score: int
    difficulty_label: str          # 'baixo' | 'médio' | 'alto'
    top_competitor_url: str | None = None
    intel_data: dict | None = None


@router.patch("/{projeto_id}/seo-plan/pages/{page_id}/intel")
async def update_seo_plan_page_intel(projeto_id: str, page_id: int, body: SeoPlanPageIntelUpdate):
    if body.difficulty_label not in ("baixo", "médio", "alto"):
        raise HTTPException(400, "difficulty_label deve ser 'baixo', 'médio' ou 'alto'")

    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]

        # T-15-01: Validar que page pertence ao projeto (evitar PATCH cross-projeto)
        row = await conn.fetchrow(
            """SELECT p.id FROM projeto_seo_plan_pages p
               JOIN projeto_seo_plan sp ON sp.id = p.plan_id
               WHERE p.id = $1 AND sp.projeto_id = $2""",
            page_id, pid_int,
        )
        if not row:
            raise HTTPException(404, "Página do plano não encontrada")

        await conn.execute(
            """UPDATE projeto_seo_plan_pages
               SET competitive_score  = $2,
                   difficulty_label   = $3,
                   top_competitor_url = $4,
                   intel_updated_at   = NOW()
               WHERE id = $1""",
            page_id,
            body.competitive_score,
            body.difficulty_label,
            body.top_competitor_url,
        )

        await conn.execute(
            """INSERT INTO projeto_seo_plan_pages_intel
               (page_id, competitive_score, difficulty_label, top_competitor_url, intel_data)
               VALUES ($1, $2, $3, $4, $5)""",
            page_id,
            body.competitive_score,
            body.difficulty_label,
            body.top_competitor_url,
            body.intel_data,
        )

    return {"ok": True}
