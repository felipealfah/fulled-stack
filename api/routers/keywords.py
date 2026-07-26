"""REQ-8-03 — POST /projetos/{projeto_id}/keywords/approve-classified.
KWMGMT-05 — GET /projetos/{projeto_id}/keywords com filtros combináveis e paginação.

Marca em massa as kw_staging pending (kw_type != 'DESCARTA') como approved
para todas as pesquisas do projeto com status IN ('classificado', 'aprovado').

Idempotente: rerun encontra 0 rows em pending → approved=0.
Auth via middleware HTTP (main.py). Não usa Depends(require_api_key) — decisão D-09.

Uso pelo agente `/seo-architect` após o Gate único da arquitetura classificada.
"""

from fastapi import APIRouter, HTTPException, Query

from db import get_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["keywords"])


@router.get("/{projeto_id}/keywords")
async def list_projeto_keywords(
    projeto_id: str,
    status: str | None = Query(default=None),
    kw_type: str | None = Query(
        default=None,
        description="Aceita valor exato ou '!VALOR' para negação (ex.: '!DESCARTA')",
    ),
    pesquisa_id: str | None = Query(default=None),
    papel: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Lista keywords de um projeto com filtros combináveis e paginação (KWMGMT-05).

    Filtros:
    - status: valor exato (ex.: 'approved', 'pending')
    - kw_type: valor exato OU '!VALOR' para negação (ex.: '!DESCARTA')
    - pesquisa_id: UUID da pesquisa de origem
    - papel: papel da pesquisa (ex.: 'principal', 'servico')
    - limit/offset: paginação (default 100/0)

    Retorna: {total: int, items: [...]}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _resolve_projeto(conn, projeto_id)

        where = ["p.projeto_id_uuid = $1::uuid"]
        params: list = [projeto_id]
        n = 2

        if status:
            where.append(f"ks.status = ${n}")
            params.append(status)
            n += 1

        if kw_type:
            if kw_type.startswith("!"):
                where.append(f"UPPER(COALESCE(ks.kw_type, '')) <> UPPER(${n})")
                params.append(kw_type[1:])
            else:
                where.append(f"ks.kw_type = ${n}")
                params.append(kw_type)
            n += 1

        if pesquisa_id:
            try:
                where.append(f"p.id = ${n}::uuid")
                params.append(pesquisa_id)
                n += 1
            except Exception:
                raise HTTPException(422, "pesquisa_id não é um UUID válido")

        if papel:
            where.append(f"p.papel = ${n}")
            params.append(papel)
            n += 1

        where_sql = " AND ".join(where)

        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM kw_staging ks JOIN pesquisas p ON p.id = ks.pesquisa_id WHERE {where_sql}",
            *params,
        )

        rows = await conn.fetch(
            f"""SELECT ks.id, ks.keyword, ks.kw_type, ks.status,
                       ks.avg_monthly_searches, ks.competitive_score, ks.difficulty_label,
                       p.id::text AS pesquisa_id, p.papel
                FROM kw_staging ks
                JOIN pesquisas p ON p.id = ks.pesquisa_id
               WHERE {where_sql}
               ORDER BY ks.avg_monthly_searches DESC NULLS LAST, ks.id ASC
               LIMIT ${n} OFFSET ${n + 1}""",
            *params, limit, offset,
        )

        return {"total": total, "items": [dict(r) for r in rows]}


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
