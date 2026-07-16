"""financeiro.py — GET /financeiro

Visão consolidada de receita da holding: MRR de todos os projetos
(receita_mensal — ex.: aluguel Rank & Rent) + financeiro da operação
de prospecção (one-off, manutenções, a receber). Usado pela página
Financeiro.tsx do dashboard.
"""

from fastapi import APIRouter

from db import get_pool

router = APIRouter(prefix="/financeiro", tags=["financeiro"])


@router.get("")
async def resumo_financeiro():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Receita recorrente declarada por projeto (qualquer tipo, projetos não encerrados)
        projetos = await conn.fetch(
            """SELECT id, projeto_nome, tipo, status, receita_mensal
               FROM projetos
               WHERE receita_mensal IS NOT NULL AND receita_mensal > 0
                 AND status != 'encerrado'
               ORDER BY receita_mensal DESC"""
        )

        # Prospecção: fechados com manutenção mensal (MRR) + one-off
        prosp = await conn.fetchrow(
            """SELECT
                 count(*) FILTER (WHERE status = 'fechado')                                         AS fechados,
                 coalesce(sum(valor_fechado)     FILTER (WHERE status = 'fechado'), 0)              AS receita_fechada,
                 coalesce(sum(manutencao_mensal) FILTER (WHERE status = 'fechado'), 0)              AS mrr,
                 coalesce(sum(valor_fechado)     FILTER (WHERE status = 'fechado' AND NOT pago), 0) AS a_receber,
                 count(*) FILTER (WHERE contrato_status = 'enviado')                                AS contratos_enviados,
                 count(*) FILTER (WHERE contrato_status = 'assinado')                               AS contratos_assinados
               FROM leads_prospeccao"""
        )
        manutencoes = await conn.fetch(
            """SELECT nome, slug, cidade, manutencao_mensal, pago, projeto_id
               FROM leads_prospeccao
               WHERE status = 'fechado' AND manutencao_mensal IS NOT NULL AND manutencao_mensal > 0
               ORDER BY manutencao_mensal DESC"""
        )

    mrr_projetos = sum(float(p["receita_mensal"]) for p in projetos)
    mrr_prospeccao = float(prosp["mrr"])
    return {
        "mrr_total": mrr_projetos + mrr_prospeccao,
        "mrr_projetos": mrr_projetos,
        "mrr_prospeccao": mrr_prospeccao,
        "projetos": [dict(p) for p in projetos],
        "prospeccao": {**dict(prosp), "manutencoes": [dict(m) for m in manutencoes]},
    }
