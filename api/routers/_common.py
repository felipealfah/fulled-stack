"""Helpers compartilhados entre routers da Stack.

_resolve_projeto: hoje vive em seo_plan.py. Extraído aqui para os routers
novos da Phase 10 (keywords, competitor_audit, backlink_intel, rank_tracking)
não copiarem a mesma implementação 4 vezes.

NÃO alterar assinatura sem atualizar seo_plan.py e os routers novos.
"""

from fastapi import HTTPException


async def _resolve_projeto(conn, projeto_id: str) -> dict:
    """Resolve UUID string para linha do projeto com id_int_legado.

    Retorna {"id": UUID, "id_int_legado": int | None}.
    Levanta HTTPException(404, "Projeto não encontrado") se UUID não existe.
    Levanta HTTPException(422, ...) se UUID mal-formatado.

    Comportamento idêntico ao helper original de seo_plan.py:26-34.
    """
    try:
        proj = await conn.fetchrow(
            "SELECT id, id_int_legado FROM projetos WHERE id = $1::uuid",
            projeto_id,
        )
    except Exception as e:
        # asyncpg levanta InvalidTextRepresentationError se UUID malformado
        msg = str(e).lower()
        if "invalid input syntax" in msg or "uuid" in msg:
            raise HTTPException(422, "projeto_id não é um UUID válido")
        raise
    if not proj:
        raise HTTPException(404, "Projeto não encontrado")
    return dict(proj)
