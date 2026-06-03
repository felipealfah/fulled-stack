from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import get_pool

router = APIRouter(prefix="/pesquisas", tags=["review"])


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    score: float | None = None
    go_nogo: str | None = None
    board_note: str | None = None
    status: str | None = None
    kw_type: str | None = None


class ApproveRequest(BaseModel):
    approved_keywords: list[str]  # textos das keywords aprovadas


@router.get("/{pesquisa_id}")
async def get_pesquisa(pesquisa_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        keywords = await conn.fetch(
            "SELECT * FROM kw_staging WHERE pesquisa_id = $1 ORDER BY score DESC NULLS LAST",
            pesquisa_id,
        )

    return {
        "pesquisa": dict(pesquisa),
        "keywords": [dict(k) for k in keywords],
        "total": len(keywords),
        "go_count": sum(1 for k in keywords if k["go_nogo"] == "GO"),
    }


@router.patch("/{pesquisa_id}/keywords/{keyword_id}")
async def update_keyword(pesquisa_id: str, keyword_id: int, body: KeywordUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        # Se kw_type está sendo alterado, lê o valor atual para logar o override
        if "kw_type" in fields:
            row = await conn.fetchrow(
                "SELECT keyword, kw_type FROM kw_staging WHERE id = $1 AND pesquisa_id = $2",
                keyword_id, pesquisa_id,
            )
            if row and row["kw_type"] is not None and row["kw_type"] != fields["kw_type"]:
                await conn.execute(
                    """INSERT INTO kw_classification_overrides
                       (pesquisa_id, keyword, classificacao_agente, classificacao_humana)
                       VALUES ($1, $2, $3, $4)""",
                    pesquisa_id, row["keyword"], row["kw_type"], fields["kw_type"],
                )

        set_clause = ", ".join(f"{k} = ${i+3}" for i, k in enumerate(fields))
        values = list(fields.values())

        await conn.execute(
            f"UPDATE kw_staging SET {set_clause} WHERE id = $1 AND pesquisa_id = $2",
            keyword_id, pesquisa_id, *values,
        )
    return {"ok": True}


@router.post("/{pesquisa_id}/approve")
async def approve_pesquisa(pesquisa_id: str, body: ApproveRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        # Marca keywords aprovadas
        await conn.execute(
            "UPDATE kw_staging SET status = 'approved' WHERE pesquisa_id = $1 AND keyword = ANY($2)",
            pesquisa_id, body.approved_keywords,
        )
        # Marca pesquisa como aprovada
        await conn.execute(
            "UPDATE pesquisas SET status = 'approved', reviewed_at = NOW() WHERE id = $1",
            pesquisa_id,
        )

    # Sinaliza para o polling container disparar o Agent 2+3 (kw_validator)
    pool2 = await get_pool()
    async with pool2.acquire() as conn:
        exec_id = await conn.fetchval(
            """INSERT INTO agent_executions
               (pesquisa_id, analysis_version, agent_name, status, started_at)
               VALUES ($1, 1, 'kw_validator', 'pending', NOW())
               RETURNING id""",
            pesquisa_id,
        )

    return {"ok": True, "agent_executions_id": str(exec_id)}


class ApproveGate2Request(BaseModel):
    projeto_id: int | None = None       # vincular a projeto existente
    criar_projeto: bool = False          # criar novo projeto a partir desta pesquisa


class PesquisaVincularUpdate(BaseModel):
    projeto_id: int | None = None
    papel: str | None = None          # 'principal' | 'servico'
    servico_slug: str | None = None


@router.post("/{pesquisa_id}/approve-gate2")
async def approve_gate2(pesquisa_id: str, body: ApproveGate2Request = ApproveGate2Request()):
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        projeto_id = body.projeto_id

        # Criar novo projeto a partir da pesquisa
        if body.criar_projeto and not projeto_id:
            row = await conn.fetchrow(
                """INSERT INTO projetos (projeto_nome, nicho, cidade, status, pesquisa_id_atual)
                   VALUES ($1, $2, $3, 'research', $4) RETURNING id""",
                pesquisa["projeto_nome"] or pesquisa["nicho"],
                pesquisa["nicho"],
                pesquisa["cidade"],
                pesquisa_id,
            )
            projeto_id = row["id"]

        # Vincular projeto existente à pesquisa atual
        if projeto_id:
            await conn.execute(
                "UPDATE projetos SET pesquisa_id_atual = $1, updated_at = NOW() WHERE id = $2",
                pesquisa_id, projeto_id,
            )

        # Atualizar pesquisa
        await conn.execute(
            """UPDATE pesquisas
               SET status = 'gate_2_approved', reviewed_at = NOW(), projeto_id = $2
               WHERE id = $1""",
            pesquisa_id, projeto_id,
        )

        # Enfileirar kw_plan_builder para regenerar plano apos Gate 2 (D-05)
        exec_id = await conn.fetchval(
            """INSERT INTO agent_executions
               (pesquisa_id, analysis_version, agent_name, status, started_at)
               VALUES ($1, 1, 'kw_plan_builder', 'pending', NOW())
               RETURNING id""",
            pesquisa_id,
        )

    return {
        "ok": True,
        "pesquisa_id": pesquisa_id,
        "status": "gate_2_approved",
        "projeto_id": projeto_id,
        "agent_executions_id": str(exec_id),
    }


@router.patch("/{pesquisa_id}/vincular")
async def vincular_pesquisa(pesquisa_id: str, body: PesquisaVincularUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not row:
            raise HTTPException(404, "Pesquisa não encontrada")

        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        values = list(fields.values())

        await conn.execute(
            f"UPDATE pesquisas SET {set_clause} WHERE id = $1",
            pesquisa_id, *values,
        )
    return {"ok": True}


@router.delete("/{pesquisa_id}/vincular")
async def desvincular_pesquisa(pesquisa_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not row:
            raise HTTPException(404, "Pesquisa não encontrada")
        await conn.execute(
            "UPDATE pesquisas SET projeto_id = NULL, papel = NULL, servico_slug = NULL WHERE id = $1",
            pesquisa_id,
        )
    return {"ok": True}


@router.delete("/{pesquisa_id}/keywords/{keyword_id}")
async def delete_keyword(pesquisa_id: str, keyword_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM kw_staging WHERE id = $1 AND pesquisa_id = $2",
            keyword_id, pesquisa_id,
        )
    if result == "DELETE 0":
        raise HTTPException(404, "Keyword não encontrada")
    return {"ok": True}


@router.delete("/{pesquisa_id}")
async def delete_pesquisa(pesquisa_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT id FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        await conn.execute("DELETE FROM kw_classification_overrides WHERE pesquisa_id = $1", pesquisa_id)
        await conn.execute("DELETE FROM scorecard_overrides WHERE pesquisa_id = $1", pesquisa_id)
        await conn.execute("DELETE FROM kw_scorecard WHERE pesquisa_id = $1", pesquisa_id)
        await conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1", pesquisa_id)
        await conn.execute("DELETE FROM agent_executions WHERE pesquisa_id = $1", pesquisa_id)
        await conn.execute(
            "UPDATE projetos SET pesquisa_id_atual = NULL WHERE pesquisa_id_atual = $1",
            pesquisa_id,
        )
        await conn.execute("DELETE FROM pesquisas WHERE id = $1", pesquisa_id)

    return {"ok": True}


@router.post("/{pesquisa_id}/reject")
async def reject_pesquisa(pesquisa_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        # Remove keywords e marca pesquisa como rejeitada
        await conn.execute("DELETE FROM kw_staging WHERE pesquisa_id = $1", pesquisa_id)
        await conn.execute(
            "UPDATE pesquisas SET status = 'rejected', reviewed_at = NOW() WHERE id = $1",
            pesquisa_id,
        )

    return {"ok": True, "message": f"Pesquisa {pesquisa_id} rejeitada e removida do staging"}


@router.get("/")
async def list_pesquisas():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT p.*, COUNT(k.id) as total_keywords FROM pesquisas p "
            "LEFT JOIN kw_staging k ON k.pesquisa_id = p.id "
            "GROUP BY p.id ORDER BY p.created_at DESC LIMIT 50"
        )
    return [dict(r) for r in rows]
