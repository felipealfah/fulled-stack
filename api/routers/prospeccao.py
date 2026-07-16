"""prospeccao.py — /prospeccao/leads

Leads da operação outbound (Full_AIOS_PROSPECTOR): CRUD usado pelos
agentes do plugin prospector e pela futura página Prospeccao.tsx do dashboard.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_pool

router = APIRouter(prefix="/prospeccao", tags=["prospeccao"])

STATUS_VALIDOS = (
    "novo", "descartado", "redesenhado", "publicado",
    "proposta_enviada", "negociacao", "fechado", "perdido", "inquilino_potencial",
)


class LeadCreate(BaseModel):
    nome: str
    slug: str
    nicho: str
    cidade: str
    projeto_id: str | None = None
    nota: float | None = None
    n_avaliacoes: int | None = None
    telefone: str | None = None
    email: str | None = None
    site_url: str | None = None
    motivo_site_ruim: str | None = None
    status: str = "novo"
    motivo_descarte: str | None = None
    notas: str | None = None


class LeadUpdate(BaseModel):
    status: str | None = None
    url_preview: str | None = None
    notas: str | None = None
    email: str | None = None
    telefone: str | None = None
    # Financeiro / contrato / follow-up (v2)
    valor_fechado: float | None = None
    manutencao_mensal: float | None = None
    pago: bool | None = None
    contrato_status: str | None = None    # 'enviado' | 'assinado'
    followup_em: str | None = None        # ISO timestamp
    respondeu_em: str | None = None       # ISO timestamp
    resumo_resposta: str | None = None
    doc_cliente: str | None = None
    end_cliente: str | None = None


@router.get("/leads")
async def list_leads(nicho: str | None = None, cidade: str | None = None,
                     status: str | None = None, projeto_id: str | None = None):
    pool = await get_pool()
    conds, params = [], []
    if nicho:
        params.append(nicho)
        conds.append(f"nicho ILIKE ${len(params)}")
    if cidade:
        params.append(cidade)
        conds.append(f"cidade ILIKE ${len(params)}")
    if status:
        params.append(status)
        conds.append(f"status = ${len(params)}")
    if projeto_id:
        params.append(projeto_id)
        conds.append(f"projeto_id = ${len(params)}::uuid")
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM leads_prospeccao {where} ORDER BY created_at DESC", *params
        )
    return [dict(r) for r in rows]


@router.get("/resumo")
async def resumo_funil(projeto_id: str | None = None):
    """Contagem de leads por status (funil) — geral ou por projeto."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if projeto_id:
            rows = await conn.fetch(
                "SELECT status, count(*) AS total FROM leads_prospeccao "
                "WHERE projeto_id = $1::uuid GROUP BY status", projeto_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT status, count(*) AS total FROM leads_prospeccao GROUP BY status"
            )
    return {r["status"]: r["total"] for r in rows}


@router.post("/leads")
async def create_leads(body: list[LeadCreate]):
    pool = await get_pool()
    criados = []
    async with pool.acquire() as conn:
        for lead in body:
            if lead.status not in STATUS_VALIDOS:
                raise HTTPException(400, f"Status inválido: {lead.status}")
            existe = await conn.fetchval(
                "SELECT 1 FROM leads_prospeccao WHERE lower(nome) = lower($1) AND lower(cidade) = lower($2)",
                lead.nome, lead.cidade,
            )
            if existe:
                raise HTTPException(409, f"Lead já existe: {lead.nome} ({lead.cidade})")
            row = await conn.fetchrow(
                """INSERT INTO leads_prospeccao
                     (nome, slug, nicho, cidade, nota, n_avaliacoes, telefone, email,
                      site_url, motivo_site_ruim, status, motivo_descarte, notas, projeto_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::uuid)
                   RETURNING *""",
                lead.nome, lead.slug, lead.nicho, lead.cidade, lead.nota,
                lead.n_avaliacoes, lead.telefone, lead.email, lead.site_url,
                lead.motivo_site_ruim, lead.status, lead.motivo_descarte, lead.notas,
                lead.projeto_id,
            )
            criados.append(dict(row))
    return criados


@router.patch("/leads/{slug}")
async def update_lead(slug: str, body: LeadUpdate):
    if body.status and body.status not in STATUS_VALIDOS:
        raise HTTPException(400, f"Status inválido: {body.status}")
    if body.contrato_status and body.contrato_status not in ("enviado", "assinado"):
        raise HTTPException(400, f"contrato_status inválido: {body.contrato_status}")

    campos = body.model_dump(exclude_none=True)
    if not campos:
        raise HTTPException(400, "Nada para atualizar")

    # Timestamps chegam como string ISO — cast no SQL
    _TS = {"followup_em", "respondeu_em"}
    if body.contrato_status == "enviado":
        campos.setdefault("contrato_em", "now()")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM leads_prospeccao WHERE slug = $1", slug)
        if not row:
            raise HTTPException(404, "Lead não encontrado")

        sets, values = [], []
        for col, val in campos.items():
            if col == "contrato_em":
                sets.append("contrato_em = now()")
                continue
            if col in _TS and isinstance(val, str):
                # asyncpg exige datetime — aceitar ISO string do CLI/agentes
                val = datetime.fromisoformat(val)
            values.append(val)
            sets.append(f"{col} = ${len(values) + 1}")
        extra = ", proposta_em = now()" if body.status == "proposta_enviada" else ""
        updated = await conn.fetchrow(
            f"UPDATE leads_prospeccao SET {', '.join(sets)}, updated_at = now(){extra} "
            f"WHERE slug = $1 RETURNING *",
            slug, *values,
        )
    return dict(updated)


@router.delete("/leads/{slug}", status_code=204)
async def delete_lead(slug: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM leads_prospeccao WHERE slug = $1 RETURNING id", slug
        )
    if not deleted:
        raise HTTPException(404, "Lead não encontrado")


@router.get("/financeiro")
async def resumo_financeiro(projeto_id: str | None = None):
    """Resumo financeiro da operação: fechados, receita one-off, MRR e a receber."""
    pool = await get_pool()
    where, params = "", []
    if projeto_id:
        params.append(projeto_id)
        where = "WHERE projeto_id = $1::uuid"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""SELECT
                  count(*) FILTER (WHERE status = 'fechado')                                   AS fechados,
                  coalesce(sum(valor_fechado)     FILTER (WHERE status = 'fechado'), 0)        AS receita_fechada,
                  coalesce(sum(manutencao_mensal) FILTER (WHERE status = 'fechado'), 0)        AS mrr,
                  coalesce(sum(valor_fechado)     FILTER (WHERE status = 'fechado' AND NOT pago), 0) AS a_receber,
                  count(*) FILTER (WHERE contrato_status = 'enviado')                          AS contratos_enviados,
                  count(*) FILTER (WHERE contrato_status = 'assinado')                         AS contratos_assinados
                FROM leads_prospeccao {where}""",
            *params,
        )
    return dict(row)
