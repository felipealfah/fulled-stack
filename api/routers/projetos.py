import asyncio
import os
import re
import sys
import unicodedata

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db import get_pool
import multica

router = APIRouter(prefix="/projetos", tags=["projetos"])

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _slugify(text: str) -> str:
    """Gera slug a partir de texto (mesmo algoritmo da Edge Function criar-projeto)."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


async def _sync_supabase(projeto_uuid: str, nome: str) -> bool:
    """POST na REST API do Supabase com UUID externo.

    Usa resolution=merge-duplicates para evitar 409 em re-sync (Pitfall 4).
    Retorna True se HTTP 200/201, False caso contrário (best-effort).
    asyncpg retorna uuid.UUID — chamar com str(row["id_uuid"]) (Pitfall 3).
    """
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        print(
            "[projetos] WARN: SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configuradas — sync ignorado",
            file=sys.stderr,
        )
        return False
    slug = _slugify(nome)
    headers = {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }
    payload = {"id": projeto_uuid, "nome": nome, "slug": slug}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_SUPABASE_URL}/rest/v1/projetos",
                headers=headers,
                json=payload,
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                print(
                    f"[projetos] Supabase sync HTTP {resp.status_code}: {resp.text[:200]}",
                    file=sys.stderr,
                )
                return False
            return True
    except Exception as e:
        print(f"[projetos] Supabase sync erro: {e}", file=sys.stderr)
        return False


def _sync_bq_map_sync(projeto_id_int: int, projeto_id_uuid: str, slug: str, nome: str) -> None:
    """Registra mapeamento UUID→INT em leadgen_gold.projetos_id_map (best-effort, síncrono).

    Chamado via loop.run_in_executor — não bloqueia o event loop.
    Pré-requisito: bq_client.ensure_projetos_id_map() e migrate_bq_add_uuid_column()
    já executados (Plan 04).
    """
    try:
        from google.cloud import bigquery as bq
        import json
        import tempfile
        from datetime import datetime, timezone

        gcp_key_json = os.environ.get("GCP_SC_KEY", "")
        if not gcp_key_json:
            print(
                "[projetos] WARN: GCP_SC_KEY não configurada — BQ map sync ignorado",
                file=sys.stderr,
            )
            return

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(gcp_key_json)
            key_path = f.name

        client = bq.Client.from_service_account_json(key_path)
        os.unlink(key_path)

        table_ref = "gifted-slice-357413.leadgen_gold.projetos_id_map"
        # DELETE+INSERT para idempotência (mesmo padrão de upsert_projetos_id_map em bq_client.py)
        del_q = f"DELETE FROM `{table_ref}` WHERE id_int = @id_int"
        jc = bq.QueryJobConfig(query_parameters=[
            bq.ScalarQueryParameter("id_int", "INT64", projeto_id_int),
        ])
        client.query(del_q, job_config=jc).result()

        row = {
            "id_int": projeto_id_int,
            "uuid": projeto_id_uuid,
            "projeto_nome": nome,
            "slug": slug,
            "criado_em": datetime.now(timezone.utc).isoformat(),
        }
        cfg = bq.LoadJobConfig(write_disposition=bq.WriteDisposition.WRITE_APPEND)
        job = client.load_table_from_json([row], table_ref, job_config=cfg)
        job.result()
        print(
            f"[projetos] BQ projetos_id_map sync OK: id_int={projeto_id_int} uuid={projeto_id_uuid}",
            flush=True,
        )
    except Exception as e:
        print(f"[projetos] WARN: BQ projetos_id_map sync falhou: {e}", file=sys.stderr)


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

    # Extrair UUID gerado pelo Postgres (Pitfall 3: asyncpg retorna uuid.UUID, não str)
    projeto_uuid = str(projeto.get("id_uuid") or projeto["id"])

    # Sincronizar UUID com Supabase CRM (best-effort)
    supabase_ok = await _sync_supabase(projeto_uuid, projeto["projeto_nome"])
    projeto["supabase_synced"] = supabase_ok
    if supabase_ok:
        print(f"[projetos] Supabase sync OK para uuid={projeto_uuid}", flush=True)
    else:
        print(f"[projetos] WARN: Supabase sync falhou para uuid={projeto_uuid}", file=sys.stderr)

    # Sincronizar mapeamento UUID→INT no BQ (best-effort, fire-and-forget)
    projeto_id_int = projeto.get("id") if isinstance(projeto.get("id"), int) else None
    if projeto_id_int is not None:
        loop = asyncio.get_running_loop()
        asyncio.create_task(
            loop.run_in_executor(
                None,
                _sync_bq_map_sync,
                projeto_id_int,
                projeto_uuid,
                _slugify(projeto["projeto_nome"]),
                projeto["projeto_nome"],
            )
        )

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


@router.get("/{projeto_id}/competitor-audit")
async def get_competitor_audit(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        projeto = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not projeto:
            raise HTTPException(404, "Projeto não encontrado")
        row = await conn.fetchrow(
            """SELECT slug, keyword_principal, generated_at, competitor_count,
                      benchmark_word_count, required_sections, schema_missing,
                      geo_pages_benchmark, backlink_benchmark, trust_gaps, summary,
                      competitors_json, yaml_path, updated_at
               FROM competitor_audits
               WHERE projeto_id = $1""",
            projeto_id,
        )
    if not row:
        return {"status": "not_found"}
    r = dict(row)
    return {
        "status": "completed",
        "slug": r["slug"],
        "keyword_principal": r["keyword_principal"],
        "generated_at": r["generated_at"],
        "competitor_count": r["competitor_count"],
        "market_gaps": {
            "benchmark_word_count": r["benchmark_word_count"],
            "required_sections": r["required_sections"] or [],
            "schema_missing": r["schema_missing"] or [],
            "geo_pages_benchmark": r["geo_pages_benchmark"],
            "backlink_benchmark": r["backlink_benchmark"],
            "trust_gaps": r["trust_gaps"] or [],
            "summary": r["summary"],
        },
        "competitors": r["competitors_json"] or [],
        "yaml_path": r["yaml_path"],
        "updated_at": r["updated_at"],
    }
