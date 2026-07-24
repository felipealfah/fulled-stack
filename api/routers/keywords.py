"""REQ-8-03 — POST /projetos/{projeto_id}/keywords/approve-classified.

Marca em massa as kw_staging pending (kw_type != 'DESCARTA') como approved
para todas as pesquisas do projeto com status IN ('classificado', 'aprovado').

Idempotente: rerun encontra 0 rows em pending → approved=0.
Auth via middleware HTTP (main.py). Não usa Depends(require_api_key) — decisão D-09.

Uso pelo agente `/seo-architect` após o Gate único da arquitetura classificada.
"""

from fastapi import APIRouter, HTTPException

from db import get_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["keywords"])


@router.post("/{projeto_id}/keywords/approve-classified")
async def approve_classified_keywords(projeto_id: str):
    """Bulk approve das kw_staging pending (kw_type != 'DESCARTA') do projeto.

    Filtro: pesquisas.status IN ('classificado', 'aprovado') AND
            kw_staging.status = 'pending' AND UPPER(kw_type) != 'DESCARTA'.

    Retorna:
        {approved: int, skipped_descarta: int, pesquisas_atualizadas: [uuid, ...]}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            proj = await _resolve_projeto(conn, projeto_id)
            pid_int = proj["id_int_legado"]
            if pid_int is None:
                raise HTTPException(
                    500, "Projeto sem id_int_legado — não pode aprovar keywords"
                )

            # Descobre pesquisas afetadas (antes do UPDATE — depois seriam approved)
            pesquisas_rows = await conn.fetch(
                """SELECT DISTINCT p.id
                     FROM pesquisas p
                     JOIN kw_staging k ON k.pesquisa_id = p.id
                    WHERE p.projeto_id = $1
                      AND p.status IN ('classificado', 'aprovado')
                      AND k.status = 'pending'
                      AND UPPER(COALESCE(k.kw_type, '')) != 'DESCARTA'""",
                pid_int,
            )
            pesquisas_atualizadas = [str(r["id"]) for r in pesquisas_rows]

            # Conta DESCARTA pendentes (skipped)
            skipped = await conn.fetchval(
                """SELECT COUNT(*)
                     FROM kw_staging k
                     JOIN pesquisas p ON p.id = k.pesquisa_id
                    WHERE p.projeto_id = $1
                      AND p.status IN ('classificado', 'aprovado')
                      AND k.status = 'pending'
                      AND UPPER(COALESCE(k.kw_type, '')) = 'DESCARTA'""",
                pid_int,
            )

            # UPDATE em massa — pré-existência do filtro garante idempotência
            result = await conn.execute(
                """UPDATE kw_staging AS k
                      SET status = 'approved', updated_at = NOW()
                     FROM pesquisas p
                    WHERE k.pesquisa_id = p.id
                      AND p.projeto_id = $1
                      AND p.status IN ('classificado', 'aprovado')
                      AND k.status = 'pending'
                      AND UPPER(COALESCE(k.kw_type, '')) != 'DESCARTA'""",
                pid_int,
            )
            # asyncpg retorna "UPDATE N"
            approved = int(result.split()[-1])

    return {
        "approved": approved,
        "skipped_descarta": int(skipped or 0),
        "pesquisas_atualizadas": pesquisas_atualizadas,
    }
