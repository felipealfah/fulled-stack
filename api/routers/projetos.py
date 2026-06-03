from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db import get_pool
import multica

router = APIRouter(prefix="/projetos", tags=["projetos"])


class ProjetoCreate(BaseModel):
    projeto_nome: str
    tipo: str = "rank_rent"
    metadata: dict = {}
    receita_mensal: float | None = None
    nicho: str = ""
    cidade: str = "Brasília"


class ProjetoUpdate(BaseModel):
    projeto_nome: str | None = None
    status: str | None = None
    metadata: dict | None = None
    receita_mensal: float | None = None


class SyncMulticaBody(BaseModel):
    multica_project_id: str | None = None


@router.get("/")
async def list_projetos(
    tipo: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if tipo and status:
            rows = await conn.fetch(
                "SELECT * FROM projetos WHERE tipo = $1 AND status = $2 ORDER BY created_at DESC",
                tipo,
                status,
            )
        elif tipo:
            rows = await conn.fetch(
                "SELECT * FROM projetos WHERE tipo = $1 ORDER BY created_at DESC",
                tipo,
            )
        elif status:
            rows = await conn.fetch(
                "SELECT * FROM projetos WHERE status = $1 ORDER BY created_at DESC",
                status,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM projetos ORDER BY created_at DESC"
            )
    return [dict(r) for r in rows]


@router.get("/{projeto_id}")
async def get_projeto(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM projetos WHERE id = $1", projeto_id
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        pesquisas = await conn.fetch(
            """SELECT id, projeto_nome, nicho, cidade, status, papel, servico_slug, created_at
               FROM pesquisas WHERE projeto_id = $1 ORDER BY papel NULLS LAST, created_at""",
            projeto_id,
        )

    return {
        **dict(row),
        "pesquisas": [dict(p) for p in pesquisas],
    }


@router.post("/")
async def create_projeto(body: ProjetoCreate):
    nicho = body.nicho or body.metadata.get("nicho", "")
    cidade = body.cidade or body.metadata.get("cidade", "Brasília")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO projetos (projeto_nome, nicho, cidade, tipo, metadata, receita_mensal, status)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'rascunho')
               RETURNING *""",
            body.projeto_nome,
            nicho,
            cidade,
            body.tipo,
            body.metadata,
            body.receita_mensal,
        )
    projeto = dict(row)

    # D-05: Sincronizar com Multica (best-effort)
    nicho = projeto.get("nicho") or (projeto.get("metadata") or {}).get("nicho", "")
    cidade = projeto.get("cidade") or (projeto.get("metadata") or {}).get("cidade", "")
    site_url = (projeto.get("metadata") or {}).get("site_url", "—")
    description = f"{projeto['tipo']} | {nicho} | {cidade} | {site_url}"
    multica_id = await multica.create_project(projeto["projeto_nome"], description)
    if multica_id:
        pool2 = await get_pool()
        async with pool2.acquire() as conn2:
            await conn2.execute(
                "UPDATE projetos SET multica_project_id = $1 WHERE id = $2",
                multica_id,
                projeto["id"],
            )
        projeto["multica_project_id"] = multica_id
        print(f"[projetos] multica_project_id={multica_id} salvo para projeto_id={projeto['id']}", flush=True)

    return projeto


@router.patch("/{projeto_id}")
async def update_projeto(projeto_id: int, body: ProjetoUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM projetos WHERE id = $1", projeto_id
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        status_anterior = row["status"]

        raw = body.model_dump()
        fields = {}
        for k, v in raw.items():
            if v is not None:
                fields[k] = v

        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        # metadata precisa de cast ::jsonb
        set_parts = []
        values = [projeto_id]
        for i, (k, v) in enumerate(fields.items(), start=2):
            if k == "metadata":
                set_parts.append(f"{k} = metadata || ${i}::jsonb")
                values.append(v)
            else:
                set_parts.append(f"{k} = ${i}")
                values.append(v)

        set_clause = ", ".join(set_parts)
        set_clause += ", updated_at = NOW()"

        updated = await conn.fetchrow(
            f"UPDATE projetos SET {set_clause} WHERE id = $1 RETURNING *",
            *values,
        )

        # D-03: Disparar rank_intel quando projeto vai para 'publicado'
        # Insere na fila agent_executions com projeto_id (nao pesquisa_id)
        novo_status = fields.get("status")
        if novo_status == "publicado" and status_anterior != "publicado":
            await conn.execute(
                """INSERT INTO agent_executions
                   (projeto_id, analysis_version, agent_name, status, started_at)
                   VALUES ($1, 1, 'rank_intel', 'pending', NOW())""",
                projeto_id,
            )
            print(f"[projetos] rank_intel enfileirado para projeto_id={projeto_id}", flush=True)

    updated_dict = dict(updated)

    # D-05: Sincronizar com Multica se projeto já tem vínculo
    multica_id_salvo = updated_dict.get("multica_project_id")
    if multica_id_salvo:
        nicho = updated_dict.get("nicho") or (updated_dict.get("metadata") or {}).get("nicho", "")
        cidade = updated_dict.get("cidade") or (updated_dict.get("metadata") or {}).get("cidade", "")
        site_url = (updated_dict.get("metadata") or {}).get("site_url", "—")
        description = f"{updated_dict['tipo']} | {nicho} | {cidade} | {site_url}"
        await multica.update_project(
            str(multica_id_salvo),
            updated_dict["projeto_nome"],
            description,
        )

    return updated_dict


@router.delete("/{projeto_id}")
async def delete_projeto(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM projetos WHERE id = $1", projeto_id
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        # D-16: nullifica projeto_id nas pesquisas antes de deletar
        await conn.execute(
            "UPDATE pesquisas SET projeto_id = NULL WHERE projeto_id = $1",
            projeto_id,
        )
        await conn.execute(
            "DELETE FROM projetos WHERE id = $1", projeto_id
        )
    return {"ok": True}


@router.post("/{projeto_id}/sync-multica")
async def sync_multica(projeto_id: int, body: SyncMulticaBody = SyncMulticaBody()):
    """Backfill: vincula projeto existente ao Multica ou força re-sync."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, projeto_nome, tipo, nicho, cidade, metadata, multica_project_id FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    projeto = dict(row)
    nicho = projeto.get("nicho") or (projeto.get("metadata") or {}).get("nicho", "")
    cidade = projeto.get("cidade") or (projeto.get("metadata") or {}).get("cidade", "")
    site_url = (projeto.get("metadata") or {}).get("site_url", "—")
    description = f"{projeto['tipo']} | {nicho} | {cidade} | {site_url}"

    multica_id_existente = str(projeto["multica_project_id"]) if projeto["multica_project_id"] else None

    if body.multica_project_id:
        # D-07: Vincular a board já existente (ex: MM Entulho)
        multica_id = body.multica_project_id
        await multica.update_project(multica_id, projeto["projeto_nome"], description)
        pool2 = await get_pool()
        async with pool2.acquire() as conn2:
            await conn2.execute(
                "UPDATE projetos SET multica_project_id = $1 WHERE id = $2",
                multica_id,
                projeto_id,
            )
        print(f"[projetos] sync-multica: projeto_id={projeto_id} vinculado a multica_id={multica_id}", flush=True)
        return {"ok": True, "action": "linked", "multica_project_id": multica_id}

    elif multica_id_existente:
        # Já tem vínculo: apenas atualizar dados
        await multica.update_project(multica_id_existente, projeto["projeto_nome"], description)
        print(f"[projetos] sync-multica: projeto_id={projeto_id} atualizado no Multica", flush=True)
        return {"ok": True, "action": "updated", "multica_project_id": multica_id_existente}

    else:
        # Sem vínculo: criar novo board no Multica
        novo_id = await multica.create_project(projeto["projeto_nome"], description)
        if novo_id:
            pool2 = await get_pool()
            async with pool2.acquire() as conn2:
                await conn2.execute(
                    "UPDATE projetos SET multica_project_id = $1 WHERE id = $2",
                    novo_id,
                    projeto_id,
                )
            print(f"[projetos] sync-multica: novo multica_project_id={novo_id} para projeto_id={projeto_id}", flush=True)
            return {"ok": True, "action": "created", "multica_project_id": novo_id}
        else:
            return {"ok": False, "action": "failed", "multica_project_id": None, "message": "Multica offline ou erro — ver logs"}


@router.get("/{projeto_id}/pipeline")
async def get_pipeline(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        projeto = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not projeto:
            raise HTTPException(404, "Projeto não encontrado")
        rows = await conn.fetch(
            """SELECT id, agent_name, status, error_message, progress_data,
                      started_at, triggered_at, completed_at, created_at
               FROM agent_executions
               WHERE projeto_id = $1
               ORDER BY created_at ASC""",
            projeto_id,
        )
    return [dict(r) for r in rows]


@router.get("/{projeto_id}/audit")
async def get_audit(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        projeto = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not projeto:
            raise HTTPException(404, "Projeto não encontrado")
        row = await conn.fetchrow(
            """SELECT id, status, progress_data, started_at, completed_at
               FROM agent_executions
               WHERE projeto_id = $1 AND agent_name = 'seo_auditor'
               ORDER BY created_at DESC LIMIT 1""",
            projeto_id,
        )
    if not row:
        return {"status": "not_found"}
    r = dict(row)
    return {
        "execution_id": r["id"],
        "status": r["status"],
        "started_at": r["started_at"],
        "completed_at": r["completed_at"],
        "data": r["progress_data"],
    }
