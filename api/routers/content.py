"""content.py — Gerenciamento de content_pages por projeto

7 endpoints:
  GET    /projetos/{projeto_id}/content                                — lista páginas de conteúdo
  POST   /projetos/{projeto_id}/content                                — upsert (cria ou atualiza sem sobrescrever approved_at)
  PATCH  /projetos/{projeto_id}/content/{page_slug}/approve            — aprova página (Board): comenta na issue se há flags; aprovado final se tudo ok
  PATCH  /projetos/{projeto_id}/content/{page_slug}/status             — atualiza status manualmente (Board override)
  PATCH  /projetos/{projeto_id}/content/{page_slug}/section            — atualiza uma seção do review_report (jsonb_set)
  POST   /projetos/{projeto_id}/content/{page_slug}/close-review       — reviewer fecha issue (comenta "Não possuem ajustes" + status done)
  DELETE /projetos/{projeto_id}/content/{page_slug}                    — remove página

Segurança (T-21-03): Parâmetros posicionais $1, $2 em todos os handlers — nunca f-string com valores de usuário.
Idempotência (T-21-04): /approve valida status='revisado' antes de UPDATE.
JSONB (T-21-05): Codec _init_conn em db.py deserializa review_report JSONB como dict Python automaticamente.
"""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import multica
from db import get_pool

CONTENT_WRITER_AGENT_NAME = os.getenv("CONTENT_WRITER_AGENT_NAME", "seo_content_writer")

router = APIRouter(prefix="/projetos", tags=["content"])


VALID_STATUSES = {'gerado', 'revisado', 'aprovado', 'revisar'}


class ContentPageUpsert(BaseModel):
    page_slug: str
    page_type: str  # home | service | service_region
    status: str     # gerado | revisado | aprovado | revisar
    review_report: dict | None = None
    multica_issue_id: str | None = None  # ID da issue do reviewer para comentar no approve


class ContentPageStatusUpdate(BaseModel):
    status: str  # gerado | revisado | aprovado | revisar


class ContentPageSectionUpdate(BaseModel):
    section: str                  # nome da seção D-03 (ex: hero, meta, reviews)
    status: str                   # ok | ajustar | flag | refazer
    issues: list[str] = []        # lista de observações (pode ser vazia)


# ---------------------------------------------------------------------------
# GET /{projeto_id}/content
# ---------------------------------------------------------------------------

@router.get("/{projeto_id}/content")
async def list_content_pages(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not proj:
            raise HTTPException(404, "Projeto não encontrado")
        rows = await conn.fetch(
            """SELECT id, projeto_id, page_slug, page_type, status,
                      review_report, reviewed_at, approved_at, created_at, updated_at
               FROM content_pages
               WHERE projeto_id = $1
               ORDER BY created_at""",
            projeto_id,
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /{projeto_id}/content
# ---------------------------------------------------------------------------

@router.post("/{projeto_id}/content")
async def upsert_content_page(projeto_id: int, body: ContentPageUpsert):
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not proj:
            raise HTTPException(404, "Projeto não encontrado")
        row = await conn.fetchrow(
            """INSERT INTO content_pages
                 (projeto_id, page_slug, page_type, status, review_report, multica_issue_id, reviewed_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, now(), now())
               ON CONFLICT (projeto_id, page_slug) DO UPDATE
                 SET status           = EXCLUDED.status,
                     review_report    = EXCLUDED.review_report,
                     multica_issue_id = COALESCE(EXCLUDED.multica_issue_id, content_pages.multica_issue_id),
                     reviewed_at      = now(),
                     updated_at       = now()
               RETURNING *""",
            projeto_id,
            body.page_slug,
            body.page_type,
            body.status,
            body.review_report,
            body.multica_issue_id,
        )
        return dict(row)


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/content/{page_slug}/approve
# ---------------------------------------------------------------------------

@router.patch("/{projeto_id}/content/{page_slug}/approve")
async def approve_content_page(projeto_id: int, page_slug: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, review_report, multica_issue_id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            projeto_id,
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

        if flagged and row["multica_issue_id"]:
            # Há seções com problemas → comentar na issue do reviewer para acionar o writer
            lines = [f"**{CONTENT_WRITER_AGENT_NAME}** correções necessárias em `{page_slug}`:\n"]
            for name, sec in flagged.items():
                issues_txt = "; ".join(sec.get("issues") or []) or "—"
                lines.append(f"- **{name}** ({sec['status']}): {issues_txt}")
            comment_body = "\n".join(lines)
            await multica.add_comment(row["multica_issue_id"], comment_body)

            updated = await conn.fetchrow(
                """UPDATE content_pages
                   SET status = 'gerado', updated_at = now()
                   WHERE projeto_id = $1 AND page_slug = $2
                   RETURNING *""",
                projeto_id,
                page_slug,
            )
            return {"triggered": True, **dict(updated)}

        # Sem flags pendentes → aprovação final
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET status = 'aprovado', approved_at = now(), updated_at = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            projeto_id,
            page_slug,
        )
        return {"triggered": False, **dict(updated)}


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/content/{page_slug}/status
# ---------------------------------------------------------------------------

@router.patch("/{projeto_id}/content/{page_slug}/status")
async def update_content_page_status(projeto_id: int, page_slug: str, body: ContentPageStatusUpdate):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Status inválido. Use: {', '.join(sorted(VALID_STATUSES))}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            projeto_id,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")
        updated = await conn.fetchrow(
            """UPDATE content_pages
               SET status = $3, updated_at = now()
               WHERE projeto_id = $1 AND page_slug = $2
               RETURNING *""",
            projeto_id,
            page_slug,
            body.status,
        )
        return dict(updated)


# ---------------------------------------------------------------------------
# DELETE /{projeto_id}/content/{page_slug}
# ---------------------------------------------------------------------------

@router.delete("/{projeto_id}/content/{page_slug}", status_code=204)
async def delete_content_page(projeto_id: int, page_slug: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            projeto_id,
            page_slug,
        )
        if result == "DELETE 0":
            raise HTTPException(404, "Página não encontrada")


# ---------------------------------------------------------------------------
# POST /{projeto_id}/content/{page_slug}/close-review
# ---------------------------------------------------------------------------

@router.post("/{projeto_id}/content/{page_slug}/close-review")
async def close_review(projeto_id: int, page_slug: str):
    """Chamado pelo AGENT-010 quando todas as seções estão ok.
    Comenta na issue do Multica e muda status para done.
    Mantém status da página como 'revisado' — Board faz aprovação final."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, multica_issue_id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            projeto_id,
            page_slug,
        )
        if not row:
            raise HTTPException(404, "Página não encontrada")

        issue_id = row["multica_issue_id"]
        commented = False
        closed = False

        if issue_id:
            commented = await multica.add_comment(
                issue_id,
                f"✅ Revisão concluída para `{page_slug}` — não possuem ajustes. Todas as seções estão ok.\n\nBoard pode aprovar no dashboard.",
            )
            closed = await multica.close_issue(issue_id, f"seo_content_reviewer: {page_slug}")

        return {"page_slug": page_slug, "issue_id": issue_id, "commented": commented, "closed": closed}


# ---------------------------------------------------------------------------
# DELETE /{projeto_id}/content/{page_slug}/section/{section_name}
# ---------------------------------------------------------------------------

@router.delete("/{projeto_id}/content/{page_slug}/section/{section_name}")
async def delete_content_page_section(projeto_id: int, page_slug: str, section_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            projeto_id,
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
            projeto_id,
            page_slug,
            section_name,
        )
        return dict(updated)


# ---------------------------------------------------------------------------
# PATCH /{projeto_id}/content/{page_slug}/section
# ---------------------------------------------------------------------------

VALID_SECTION_STATUSES = {'ok', 'ajustar', 'flag', 'refazer'}


@router.patch("/{projeto_id}/content/{page_slug}/section")
async def update_content_page_section(projeto_id: int, page_slug: str, body: ContentPageSectionUpdate):
    if body.status not in VALID_SECTION_STATUSES:
        raise HTTPException(400, f"Status de seção inválido. Use: {', '.join(sorted(VALID_SECTION_STATUSES))}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, review_report FROM content_pages WHERE projeto_id = $1 AND page_slug = $2",
            projeto_id,
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
            projeto_id,
            page_slug,
            body.section,
            section_data,
        )
        return dict(updated)
