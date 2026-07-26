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
from pydantic import BaseModel, Field

from db import get_pool

router = APIRouter(prefix="/projetos", tags=["seo-plan"])

CANONICAL_TO_PT_DIFFICULTY = {"LOW": "baixo", "MED": "médio", "HIGH": "alto"}

TIPO_TO_PAGE_TYPE = {
    "home": "home",
    "servico": "service",
    "servico_geo": "service_region",
    "localidade": "localidade",
}

ALLOWED_KW_TYPES_PAGES = {
    "PAGINA_PRINCIPAL", "PAGINA_GEO", "LOCALIDADE",
    "SECAO", "SURPRESA", "DESCARTA", "SERVICO",
}


def _derive_page_slug(url: str) -> str:
    return url.strip("/").split("/")[-1] or "home"


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


# ---------------------------------------------------------------------------
# POST /{projeto_id}/seo-plan/populate-intel
# Phase 32 — Bulk populate intel from kw_staging into seo-plan pages
# ---------------------------------------------------------------------------

@router.post("/{projeto_id}/seo-plan/populate-intel")
async def populate_intel(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]
        if pid_int is None:
            raise HTTPException(422, "Projeto sem id_int_legado — não há seo_plan associado")

        pages = await conn.fetch(
            """SELECT p.id AS page_id, p.pesquisa_id, p.kw_principal_id
               FROM projeto_seo_plan_pages p
               JOIN projeto_seo_plan sp ON sp.id = p.plan_id
               WHERE sp.projeto_id = $1 AND p.pesquisa_id IS NOT NULL""",
            pid_int,
        )

        if not pages:
            return {"pages_updated": 0, "pages_sem_intel": []}

        pages_updated = 0
        pages_sem_intel: list[int] = []

        async with conn.transaction():
            for pg in pages:
                if pg["kw_principal_id"] is not None:
                    intel = await conn.fetchrow(
                        "SELECT competitive_score, difficulty_label, top_competitor_url FROM kw_staging WHERE id = $1",
                        pg["kw_principal_id"],
                    )
                else:
                    intel = await conn.fetchrow(
                        """SELECT competitive_score, difficulty_label, top_competitor_url
                           FROM kw_staging
                           WHERE pesquisa_id = $1 AND competitive_score IS NOT NULL
                           ORDER BY competitive_score DESC NULLS LAST
                           LIMIT 1""",
                        pg["pesquisa_id"],
                    )

                if intel is None or intel["competitive_score"] is None:
                    pages_sem_intel.append(pg["page_id"])
                    continue

                mapped_difficulty = CANONICAL_TO_PT_DIFFICULTY.get(
                    intel["difficulty_label"], intel["difficulty_label"]
                )

                await conn.execute(
                    """UPDATE projeto_seo_plan_pages
                       SET competitive_score = $2,
                           difficulty_label = $3,
                           top_competitor_url = $4,
                           intel_updated_at = NOW()
                       WHERE id = $1""",
                    pg["page_id"],
                    int(intel["competitive_score"]) if intel["competitive_score"] is not None else None,
                    mapped_difficulty,
                    intel["top_competitor_url"],
                )
                pages_updated += 1

    return {"pages_updated": pages_updated, "pages_sem_intel": pages_sem_intel}


# ---------------------------------------------------------------------------
# PUT /{projeto_id}/seo-plan/pages/sync
# Phase 32 — Sync estrutural de páginas do vault em content_pages (KWMGMT-02)
# ---------------------------------------------------------------------------

class PageStructuralItem(BaseModel):
    url: str
    tipo: str
    kw_type: str | None = None
    titulo: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    keyword_primaria: str | None = None
    pesquisa_id: str | None = None
    papel_pesquisa: str | None = None
    servico_pai: str | None = None
    sem_volume: bool = False


class SyncPagesRequest(BaseModel):
    replace: bool = False
    pages: list[PageStructuralItem] = Field(default=[], max_length=2000)


@router.put("/{projeto_id}/seo-plan/pages/sync")
async def sync_seo_plan_pages(projeto_id: str, body: SyncPagesRequest):
    import uuid as _uuid
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        pid_int = proj["id_int_legado"]
        if pid_int is None:
            raise HTTPException(422, "Projeto sem id_int_legado — impossível gravar em content_pages")
        projeto_uuid_str = str(proj["id"])

        invalid: list[dict] = []
        valid: list[dict] = []

        for page in body.pages:
            if not page.url or not page.url.strip():
                invalid.append({"url": page.url, "reason": "url vazia"})
                continue
            if page.tipo not in TIPO_TO_PAGE_TYPE:
                invalid.append({"url": page.url, "reason": "tipo desconhecido: " + page.tipo})
                continue
            if page.kw_type is not None and page.kw_type not in ALLOWED_KW_TYPES_PAGES:
                invalid.append({"url": page.url, "reason": "kw_type inválido: " + page.kw_type})
                continue
            pesquisa_id_val = None
            if page.pesquisa_id:
                try:
                    _uuid.UUID(page.pesquisa_id)
                    pesquisa_id_val = page.pesquisa_id
                except ValueError:
                    invalid.append({"url": page.url, "reason": "pesquisa_id não é UUID válido"})
                    continue
            valid.append({
                "url": page.url.strip(),
                "page_type": TIPO_TO_PAGE_TYPE[page.tipo],
                "page_slug": _derive_page_slug(page.url),
                "titulo": page.titulo,
                "meta_description": page.meta_description,
                "h1": page.h1,
                "kw_type": page.kw_type,
                "keyword_primaria": page.keyword_primaria,
                "pesquisa_id": pesquisa_id_val,
                "papel_pesquisa": page.papel_pesquisa,
                "servico_pai": page.servico_pai,
                "sem_volume": page.sem_volume,
            })

        created = 0
        updated = 0
        archived = 0

        async with conn.transaction():
            for v in valid:
                row = await conn.fetchrow(
                    """INSERT INTO content_pages (
                         projeto_id, projeto_id_uuid, page_slug, page_type,
                         url, titulo, meta_description, h1, kw_type, keyword_primaria,
                         sem_volume, pesquisa_id, papel_pesquisa, servico_pai,
                         synced_at, arquivada, status, created_at, updated_at
                       ) VALUES (
                         $1, $2::uuid, $3, $4,
                         $5, $6, $7, $8, $9, $10,
                         $11, $12::uuid, $13, $14,
                         NOW(), false, 'gerado', NOW(), NOW()
                       )
                       ON CONFLICT (projeto_id, url) WHERE url IS NOT NULL DO UPDATE
                         SET titulo           = EXCLUDED.titulo,
                             meta_description = EXCLUDED.meta_description,
                             h1               = EXCLUDED.h1,
                             kw_type          = EXCLUDED.kw_type,
                             keyword_primaria = EXCLUDED.keyword_primaria,
                             sem_volume       = EXCLUDED.sem_volume,
                             pesquisa_id      = EXCLUDED.pesquisa_id,
                             papel_pesquisa   = EXCLUDED.papel_pesquisa,
                             servico_pai      = EXCLUDED.servico_pai,
                             synced_at        = NOW(),
                             arquivada        = false,
                             updated_at       = NOW()
                       RETURNING (xmax = 0) AS was_inserted""",
                    pid_int, projeto_uuid_str, v["page_slug"], v["page_type"],
                    v["url"], v["titulo"], v["meta_description"], v["h1"],
                    v["kw_type"], v["keyword_primaria"],
                    v["sem_volume"], v["pesquisa_id"], v["papel_pesquisa"], v["servico_pai"],
                )
                if row["was_inserted"]:
                    created += 1
                else:
                    updated += 1

            if body.replace and valid:
                payload_urls = [v["url"] for v in valid]
                result = await conn.execute(
                    """UPDATE content_pages
                          SET arquivada = true, updated_at = NOW()
                        WHERE projeto_id = $1
                          AND url IS NOT NULL
                          AND arquivada = false
                          AND url <> ALL($2::text[])""",
                    pid_int, payload_urls,
                )
                archived = int(result.split()[-1])

    return {"created": created, "updated": updated, "archived": archived, "invalid": invalid}
