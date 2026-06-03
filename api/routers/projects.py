from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import get_pool

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    projeto_nome: str
    nicho: str
    cidade: str = "Brasília"


@router.get("/")
async def list_projects():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM projetos ORDER BY created_at DESC")
    return [dict(r) for r in rows]


@router.post("/")
async def create_project(body: ProjectCreate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO projetos (projeto_nome, nicho, cidade) VALUES ($1, $2, $3) RETURNING *",
            body.projeto_nome, body.nicho, body.cidade,
        )
    return dict(row)


@router.get("/{projeto_nome}")
async def get_project(projeto_nome: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM projetos WHERE projeto_nome = $1", projeto_nome
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")
    return dict(row)
