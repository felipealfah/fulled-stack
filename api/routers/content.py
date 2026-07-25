"""content.py — Gerenciamento de content_pages por projeto

7 endpoints (todos aceitam projeto_id como UUID string):
  GET    /projetos/{projeto_id}/content                                — lista páginas de conteúdo
  POST   /projetos/{projeto_id}/content                                — upsert (cria ou atualiza sem sobrescrever approved_at)
  PATCH  /projetos/{projeto_id}/content/{page_slug}/approve            — aprova página (Board): retorna flagged_sections se há pendências; aprovado final se tudo ok
  PATCH  /projetos/{projeto_id}/content/{page_slug}/status             — atualiza status manualmente (Board override)
  PATCH  /projetos/{projeto_id}/content/{page_slug}/section            — atualiza uma seção do review_report (jsonb_set)
  POST   /projetos/{projeto_id}/content/{page_slug}/close-review       — sinaliza revisão concluída: atualiza status para 'revisado', Board aprova via /approve
  DELETE /projetos/{projeto_id}/content/{page_slug}                    — remove página
  DELETE /projetos/{projeto_id}/content/{page_slug}/section/{section_name} — remove uma seção do review_report

## Phase 12-02 fix — path param passa a ser UUID (str)
`content_pages.projeto_id` continua INTEGER (unique constraint natural
`(projeto_id, page_slug)`), então internamente resolvemos o UUID para
`id_int_legado` via `_resolve_projeto` antes do INSERT/SELECT. Também
populamos `projeto_id_uuid` para que o dashboard scoped por projeto enxergue
as rows. Antes desta correção, todos os 7 endpoints estavam órfãos da
migração UUID (Phase 05) e retornavam 500/422 em prod.

Segurança (T-21-03): Parâmetros posicionais $1, $2 em todos os handlers — nunca f-string com valores de usuário.
Idempotência (T-21-04): /approve valida status='revisado' antes de UPDATE.
JSONB (T-21-05): Codec _init_conn em db.py deserializa review_report JSONB como dict Python automaticamente.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["content"])


VALID_STATUSES = {'gerado', 'revisado', 'aprovado', 'revisar'}


class ContentPageUpsert(BaseModel):
    page_slug: str
    page_type: str  # home | service | service_region | localidade (v2)
    status: str     # gerado | revisado | aprovado | revisar
    review_report: dict | None = None


class ContentPageStatusUpdate(BaseModel):
    status: str  # gerado | revisado | aprovado | revisar


class ContentPageSectionUpdate(BaseModel):
    section: str                  # nome da seção D-03 (ex: hero, meta, reviews)
    status: str                   # ok | ajustar | flag | refazer
    issues: list[str] = []        # lista de observações (pode ser vazia)


async def _resolve_projeto_id_int(conn, projeto_id: str) -> int:
    """Resolve UUID string → id_int_legado (INT). 404 se projeto não existe.
    422 se id_int_legado ausente (projeto criado antes da Phase 05 sem swap)."""
    proj = await _resolve_projeto(conn, projeto_id)
    id_int = proj.get("id_int_legado")
    if id_int is None:
        raise HTTPException(
            422,
            "Projeto sem id_int_legado — content_pages ainda usa FK INTEGER; "
            "rode o backfill da Phase 05 antes de usar este endpoint.",
        )
    return id_int


# ---------------------------------------------------------------------------
# GET /{projeto_id}/content
# ---------------------------------------------------------------------------

@router.get("/{projeto_id}/content")
async def list_content_pages(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        rows = await conn.fetch(
            """SELECT id, projeto_id, projeto_id_uuid, page_slug, page_type, status,
                      review_report, reviewed_at, approved_at, created_at, updated_at
               FROM content_pages
               WHERE projeto_id = $1
               ORDER BY created_at""",
            id_int,
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /{projeto_id}/content
# ---------------------------------------------------------------------------

@router.post("/{projeto_id}/content")
async def upsert_content_page(projeto_id: str, body: ContentPageUpsert):
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        row = await conn.fetchrow(
            """INSERT INTO content_pages
                 (projeto_id, projeto_id_uuid, page_slug, page_type, status, review_report, reviewed_at, updated_at)
               VALUES ($1, $2::uuid, $3, $4, $5, $6, now(), now())
               ON CONFLICT (projeto_id, page_slug) DO UPDATE
                 SET status          = EXCLUDED.status,
                     review_report   = EXCLUDED.review_report,
                     projeto_id_uuid = EXCLUDED.projeto_id_uuid,
                     reviewed_at     = now(),
                     updated_at      = now()
               RETURNING *""",
            id_int,
            projeto_id,
            body.page_slug,
            body.page_type,
            body.status,
            body.review_report,
        )
        return dict(row)


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/content/{page_slug}/approve
# ---------------------------------------------------------------------------

@router.patch("/{projeto_id}/content/{page_slug}/approve")
async def approve_content_page(projeto_id: str, page_slug: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        row = await conn.fetchrow(
            "SELECT id, status, review_report FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            id_int,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")
        if row["status"] != "revisado":
            raise HTTPException(400, "Página não está em status revisado")

        review = row["review_report"] or {}
        sections = review.get("sections", {})
        flagged = {
            name: sec for name, sec in sections.items()
            if sec.get("status") in ("ajustar", "flag", "refazer")
        }

        # Board aprova em qualquer caso — flags são informacionais.
        # triggered=True indica que havia pendências no momento da aprovação (fica registrado).
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET status = 'aprovado', approved_at = now(), updated_at = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            id_int,
            page_slug,
        )
        return {
            "triggered": bool(flagged),
            "flagged_sections": list(flagged.keys()),
            **dict(updated),
        }


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/content/{page_slug}/status
# ---------------------------------------------------------------------------

@router.patch("/{projeto_id}/content/{page_slug}/status")
async def update_content_page_status(projeto_id: str, page_slug: str, body: ContentPageStatusUpdate):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Status inválido. Use: {', '.join(sorted(VALID_STATUSES))}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        row = await conn.fetchrow(
            "SELECT id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            id_int,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET status = $3, updated_at = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            id_int,
            page_slug,
            body.status,
        )
        return dict(updated)


# ---------------------------------------------------------------------------
# DELETE /{projeto_id}/content/{page_slug}
# ---------------------------------------------------------------------------

@router.delete("/{projeto_id}/content/{page_slug}", status_code=204)
async def delete_content_page(projeto_id: str, page_slug: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        result = await conn.execute(
            "DELETE FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            id_int,
            page_slug,
        )
        if result == "DELETE 0":
            raise HTTPException(404, "Página não encontrada")


# ---------------------------------------------------------------------------
# POST /{projeto_id}/content/{page_slug}/close-review
# ---------------------------------------------------------------------------

@router.post("/{projeto_id}/content/{page_slug}/close-review")
async def close_review(projeto_id: str, page_slug: str):
    """Sinaliza revisão concluída (todas as seções ok). Atualiza status para 'revisado'.
    Board faz aprovação final via /approve."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        row = await conn.fetchrow(
            "SELECT id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            id_int,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET status = 'revisado', reviewed_at = now(), updated_at = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            id_int,
            page_slug,
        )
        return dict(updated)


# ---------------------------------------------------------------------------
# DELETE /{projeto_id}/content/{page_slug}/section/{section_name}
# ---------------------------------------------------------------------------

@router.delete("/{projeto_id}/content/{page_slug}/section/{section_name}")
async def delete_content_page_section(projeto_id: str, page_slug: str, section_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        row = await conn.fetchrow(
            "SELECT id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            id_int,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET review_report = review_report #- ARRAY['sections', $3],
                   updated_at    = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            id_int,
            page_slug,
            section_name,
        )
        return dict(updated)


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/content/{page_slug}/section
# ---------------------------------------------------------------------------

VALID_SECTION_STATUSES = {'ok', 'ajustar', 'flag', 'refazer'}


@router.patch("/{projeto_id}/content/{page_slug}/section")
async def update_content_page_section(projeto_id: str, page_slug: str, body: ContentPageSectionUpdate):
    if body.status not in VALID_SECTION_STATUSES:
        raise HTTPException(400, f"Status de seção inválido. Use: {', '.join(sorted(VALID_SECTION_STATUSES))}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        id_int = await _resolve_projeto_id_int(conn, projeto_id)
        row = await conn.fetchrow(
            "SELECT id, review_report FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            id_int,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")
        import json
        section_data = json.dumps({"status": body.status, "issues": body.issues}, ensure_ascii=False)
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET review_report = jsonb_set(
                     COALESCE(review_report, '{"sections": {}}'::jsonb),
                     ARRAY['sections', $3],
                     $4::jsonb,
                     true
                   ),
                   updated_at = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            id_int,
            page_slug,
            body.section,
            section_data,
        )
        return dict(updated)
