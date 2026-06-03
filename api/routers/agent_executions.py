from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from db import get_pool

router = APIRouter(prefix="/agent-executions", tags=["agent-executions"])


class AgentExecutionCreate(BaseModel):
    pesquisa_id: str
    agent_name: str
    analysis_version: int = 1
    status: str = "in_progress"


class AgentExecutionUpdate(BaseModel):
    status: Optional[str] = None
    error_message: Optional[str] = None
    progress_data: Optional[dict] = None


@router.post("/")
async def create_execution(body: AgentExecutionCreate):
    """Registra início de execução de um agente. Retorna o execution_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT id FROM pesquisas WHERE id = $1", body.pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        row = await conn.fetchrow(
            """INSERT INTO agent_executions
               (pesquisa_id, analysis_version, agent_name, status, started_at)
               VALUES ($1, $2, $3, $4, NOW())
               RETURNING id""",
            body.pesquisa_id, body.analysis_version, body.agent_name, body.status,
        )
    return {"id": row["id"], "status": body.status}


@router.patch("/{execution_id}")
async def update_execution(execution_id: int, body: AgentExecutionUpdate):
    """Atualiza status de uma execução (in_progress → completed ou failed)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        execution = await conn.fetchrow(
            "SELECT id FROM agent_executions WHERE id = $1", execution_id
        )
        if not execution:
            raise HTTPException(404, "Execução não encontrada")

        fields = {}
        if body.status is not None:
            fields["status"] = body.status
        if body.error_message is not None:
            fields["error_message"] = body.error_message
        if body.progress_data is not None:
            fields["progress_data"] = body.progress_data

        # Sempre atualizar updated_at
        fields["updated_at"] = datetime.now(timezone.utc)

        # Se status = completed, registrar completed_at automaticamente
        if body.status == "completed":
            fields["completed_at"] = datetime.now(timezone.utc)

        if len(fields) <= 1:
            # Apenas updated_at — nenhum campo real fornecido
            raise HTTPException(400, "Nenhum campo para atualizar")

        set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        values = list(fields.values())

        await conn.execute(
            f"UPDATE agent_executions SET {set_clause} WHERE id = $1",
            execution_id, *values,
        )
    return {"ok": True}


@router.get("/pesquisa/{pesquisa_id}")
async def list_executions(pesquisa_id: str):
    """Lista execuções de agentes para uma pesquisa (para debug e rastreamento)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, agent_name, status, error_message, started_at, completed_at, retry_count
               FROM agent_executions
               WHERE pesquisa_id = $1
               ORDER BY created_at DESC""",
            pesquisa_id,
        )
    return [dict(r) for r in rows]
