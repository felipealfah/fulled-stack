import asyncio
import os
import re
import sys
import unicodedata

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db import get_pool
from db_leadgen import get_lg_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["projetos"])

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_SUPABASE_ADMIN_USER_ID = os.environ.get("SUPABASE_ADMIN_USER_ID", "")


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

            # Vincular admin como membro do projeto (idempotente via ON CONFLICT DO NOTHING)
            if _SUPABASE_ADMIN_USER_ID:
                await client.post(
                    f"{_SUPABASE_URL}/rest/v1/usuarios_projetos",
                    headers={**headers, "Prefer": "return=minimal,resolution=ignore-duplicates"},
                    json={"user_id": _SUPABASE_ADMIN_USER_ID, "projeto_id": projeto_uuid, "role": "admin"},
                    timeout=10,
                )

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


class AgentExecutionByProjetoCreate(BaseModel):
    """Body para POST /projetos/{id}/agent-executions (Plan 12-02).

    `pesquisa_id` opcional — permite site-builder rodar sem pesquisa aprovada.
    Handler grava AMBOS `projeto_id` (INT via id_int_legado) e
    `projeto_id_uuid` (UUID) para preencher o dashboard scoped por projeto.
    """
    agent_name: str
    status: str = "completed"  # pending | in_progress | completed | failed
    pesquisa_id: str | None = None
    analysis_version: int = 1
    error_message: str | None = None


@router.get("/")
async def list_projetos(
    tipo: str | None = Query(default=None),
    status: str | None = Query(default=None),
    id_int_legado: int | None = Query(
        default=None,
        description="Filtro exato pelo ID inteiro legado (KWMGMT-06)",
    ),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        where: list[str] = []
        params: list = []
        n = 1

        if tipo:
            where.append(f"tipo = ${n}")
            params.append(tipo)
            n += 1

        if status:
            where.append(f"status = ${n}")
            params.append(status)
            n += 1

        if id_int_legado is not None:
            where.append(f"id_int_legado = ${n}")
            params.append(id_int_legado)
            n += 1

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = await conn.fetch(
            f"SELECT * FROM projetos {where_sql} ORDER BY created_at DESC",
            *params,
        )
    return [dict(r) for r in rows]


@router.get("/{projeto_id}")
async def get_projeto(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM projetos WHERE id = $1", projeto_id
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        pesquisas = await conn.fetch(
            """SELECT id, projeto_nome, nicho, cidade, status, papel, servico_slug, created_at
               FROM pesquisas WHERE projeto_id_uuid = $1 ORDER BY papel NULLS LAST, created_at""",
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

    # Supabase CRM: sync ocorre apenas quando projeto vai para 'publicado' (não na criação)

    # Sincronizar mapeamento UUID→INT no BQ (best-effort, fire-and-forget)
    # run_in_executor retorna Future (não coroutine) — usar ensure_future para agendar
    # Após Phase 05: projeto["id"] é UUID — o inteiro legado está em id_int_legado
    projeto_id_int = projeto.get("id_int_legado")
    if projeto_id_int is not None:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(
            loop.run_in_executor(
                None,
                _sync_bq_map_sync,
                projeto_id_int,
                projeto_uuid,
                _slugify(projeto["projeto_nome"]),
                projeto["projeto_nome"],
            )
        )

    return projeto


@router.patch("/{projeto_id}")
async def update_projeto(projeto_id: str, body: ProjetoUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, tipo FROM projetos WHERE id = $1", projeto_id
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

        status_anterior = row["status"]
        tipo = row["tipo"]

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
        # Insere na fila agent_executions populando AMBOS projeto_id (INT legado)
        # E projeto_id_uuid (UUID moderno). Phase 12-02: sem popular UUID, o
        # dashboard scoped por projeto não enxergava a execução.
        novo_status = fields.get("status")
        if novo_status == "publicado" and status_anterior != "publicado":
            id_int = await conn.fetchval(
                "SELECT id_int_legado FROM projetos WHERE id = $1", projeto_id
            )
            await conn.execute(
                """INSERT INTO agent_executions
                   (projeto_id, projeto_id_uuid, analysis_version, agent_name, status, started_at)
                   VALUES ($1, $2::uuid, 1, 'rank_intel', 'pending', NOW())""",
                id_int, projeto_id,
            )
            print(f"[projetos] rank_intel enfileirado para projeto_id={projeto_id} (id_int={id_int})", flush=True)

        # Sincronizar com Supabase CRM quando projeto vai para 'publicado' (rank_rent only)
        if novo_status == "publicado" and status_anterior != "publicado" and tipo == "rank_rent":
            projeto_nome = dict(updated)["projeto_nome"]
            supabase_ok = await _sync_supabase(projeto_id, projeto_nome)
            if supabase_ok:
                print(f"[projetos] Supabase sync OK ao publicar uuid={projeto_id}", flush=True)
            else:
                print(f"[projetos] WARN: Supabase sync falhou ao publicar uuid={projeto_id}", file=sys.stderr)

    return dict(updated)


# Fase 35 / D-06: as 6 tabelas que tinham `ON DELETE CASCADE` para `projetos` e mudaram de
# banco. Conferido no catálogo do Postgres vivo (`pg_constraint.confdeltype = 'c'`), não na
# lista do plano — que omitia `backlink_intel`.
#
# A coluna difere: `backlink_intel` referencia o projeto por `projeto_id` (a PK natural da
# tabela); as outras cinco por `projeto_id_uuid`.
#
# NÃO entram aqui `projeto_seo_plan_pages` e `projeto_seo_plan_pages_intel`: as FKs delas
# apontam para dentro do próprio schema `leadgen` e continuam sendo cascade de banco de
# verdade — apagar `projeto_seo_plan` já as leva junto.
_TABELAS_CASCADE_PERDIDO = (
    ("competitor_audits", "projeto_id_uuid"),
    ("content_pages", "projeto_id_uuid"),
    ("projeto_geo_targets", "projeto_id_uuid"),
    ("projeto_seo_plan", "projeto_id_uuid"),
    ("rank_intel_overrides", "projeto_id_uuid"),
    ("backlink_intel", "projeto_id"),
)


@router.delete("/{projeto_id}")
async def delete_projeto(projeto_id: str):
    """Apaga o projeto e tudo que dependia dele.

    ## Fase 35 / D-06 — o cascade do banco não existe mais
    ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    Antes, um único `DELETE FROM projetos` disparava 6 `ON DELETE CASCADE`. Essas 6 tabelas
    moram agora no Supabase e não há FK atravessando a fronteira dos bancos: sem limpeza
    explícita o delete passaria a deixar lixo invisível, que só apareceria meses depois como
    dado fantasma. As três etapas abaixo são ordenadas de propósito.

    Filhos primeiro, projeto por último: a intenção do endpoint é destrutiva, então uma
    falha no passo 3 deixa o projeto vivo **sem** filhos, e reexecutar o `DELETE` converge
    (o passo 2 vira no-op). A ordem inversa deixaria órfãos permanentes e invisíveis.
    """
    # Passo 1 — resolver o projeto no Postgres (camada de decisão). 404/422 em pt-BR.
    pg = await get_pool()
    async with pg.acquire() as c_pg:
        proj = await _resolve_projeto(c_pg, projeto_id)
    pid_uuid = str(proj["id"])

    # Passo 2 — Fase 35 / D-06: apagar os filhos no Supabase, numa transação só.
    lg = await get_lg_pool()
    async with lg.acquire() as c_lg:
        async with c_lg.transaction():
            for tabela, coluna in _TABELAS_CASCADE_PERDIDO:
                # noqa S608: identificadores vêm de _TABELAS_CASCADE_PERDIDO (constante
                # do módulo), nunca de entrada do usuário; o único valor continua
                # parametrizado em $1 (T-35-06). É o caso de "SET dinâmico" que o
                # CLAUDE.md abre como exceção — nome de coluna por f-string, valor nunca.
                await c_lg.execute(
                    f"DELETE FROM {tabela} WHERE {coluna} = $1::uuid", pid_uuid,  # noqa: S608
                )

    # Passo 3 — só então o Postgres.
    try:
        async with pg.acquire() as c_pg:
            async with c_pg.transaction():
                # D-16: nullifica projeto_id_uuid nas pesquisas antes de deletar
                await c_pg.execute(
                    "UPDATE pesquisas SET projeto_id_uuid = NULL WHERE projeto_id_uuid = $1::uuid",
                    pid_uuid,
                )
                await c_pg.execute("DELETE FROM projetos WHERE id = $1::uuid", pid_uuid)
    except Exception as e:
        # Nunca falhar mudo: os filhos já foram apagados e o projeto continua de pé.
        print(
            f"[projetos] WARN: filhos de uuid={pid_uuid} apagados no Supabase mas o DELETE "
            f"no Postgres falhou: {type(e).__name__}",
            file=sys.stderr,
        )
        raise HTTPException(
            500,
            "Os dados dependentes do projeto foram apagados, mas o projeto em si não pôde "
            "ser removido. Reexecute o DELETE para concluir — a operação é idempotente.",
        )

    return {"ok": True}


@router.get("/{projeto_id}/pipeline")
async def get_pipeline(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        projeto = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not projeto:
            raise HTTPException(404, "Projeto não encontrado")
        rows = await conn.fetch(
            """SELECT id, agent_name, status, error_message, progress_data,
                      started_at, triggered_at, completed_at, created_at
               FROM agent_executions
               WHERE projeto_id_uuid = $1
               ORDER BY created_at ASC""",
            projeto_id,
        )
    return [dict(r) for r in rows]


@router.post("/{projeto_id}/agent-executions", status_code=201)
async def create_execution_by_projeto(projeto_id: str, body: AgentExecutionByProjetoCreate):
    """Cria agent_execution vinculada a projeto (pesquisa_id opcional).

    Motivação Plan 12-02: skills content/site precisam registrar execuções
    scoped por projeto — content-writer/content-reviewer preferencialmente
    também vinculam à pesquisa (quando existe), site-builder roda antes de
    ter pesquisa aprovada. Este endpoint substitui os `docker exec ... psql`
    das 3 skills e o `POST /agent-executions/` legado (que exige pesquisa_id
    obrigatório).

    Popula AMBOS `projeto_id` (INT via id_int_legado, coluna legada) E
    `projeto_id_uuid` (FK canônica pós-Phase 05) — assim o dashboard
    scoped por projeto enxerga a execução.

    Retorna 201 + `{id, projeto_id, status}`.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto_id_int_local(conn, projeto_id)
        id_int = proj["id_int_legado"]

        # Se pesquisa_id foi passado, validar que existe (soft check — não bloqueia se ausente)
        if body.pesquisa_id:
            pesq = await conn.fetchrow(
                "SELECT id FROM pesquisas WHERE id = $1::uuid", body.pesquisa_id
            )
            if not pesq:
                raise HTTPException(404, "Pesquisa informada não encontrada")

        # Se status='completed', gravar completed_at automaticamente
        completed_at_sql = "NOW()" if body.status == "completed" else "NULL"

        row = await conn.fetchrow(
            f"""INSERT INTO agent_executions
                (projeto_id, projeto_id_uuid, pesquisa_id,
                 analysis_version, agent_name, status,
                 started_at, completed_at, error_message)
                VALUES ($1, $2::uuid, $3, $4, $5, $6, NOW(), {completed_at_sql}, $7)
                RETURNING id""",
            id_int,
            projeto_id,
            body.pesquisa_id,
            body.analysis_version,
            body.agent_name,
            body.status,
            body.error_message,
        )
    return {
        "id": row["id"],
        "projeto_id": projeto_id,
        "status": body.status,
    }


async def _resolve_projeto_id_int_local(conn, projeto_id: str) -> dict:
    """Resolve UUID → {"id_int_legado": int}. 404 se projeto não existe.
    Definido aqui para evitar acoplamento circular com _common quando o
    handler novo virou permanente. Se `id_int_legado` for None (projeto
    criado antes da Phase 05), levanta 422 com mensagem clara.
    """
    row = await conn.fetchrow(
        "SELECT id, id_int_legado FROM projetos WHERE id = $1::uuid", projeto_id,
    )
    if not row:
        raise HTTPException(404, "Projeto não encontrado")
    if row["id_int_legado"] is None:
        raise HTTPException(
            422,
            "Projeto sem id_int_legado — agent_executions ainda usa FK INTEGER "
            "para retro-compat; rode o backfill da Phase 05 antes de usar este endpoint.",
        )
    return {"id": row["id"], "id_int_legado": row["id_int_legado"]}


@router.get("/{projeto_id}/audit")
async def get_audit(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        projeto = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not projeto:
            raise HTTPException(404, "Projeto não encontrado")
        row = await conn.fetchrow(
            """SELECT id, status, progress_data, started_at, completed_at
               FROM agent_executions
               WHERE projeto_id_uuid = $1 AND agent_name = 'seo_auditor'
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
async def get_competitor_audit(projeto_id: str):
    """Leitura do competitor_audit do projeto.

    Fase 35 / D-02: única leitura de tabela migrada neste arquivo. O `SELECT id FROM
    projetos` continua no Postgres; o SELECT de `competitor_audits` passou ao Supabase.

    ⚠️ Este SELECT referencia `backlink_benchmark`, coluna que nunca existiu em banco
    nenhum — o endpoint responde 500 até a migration 034 (Stack) / 20260830120000
    (Supabase) serem aplicadas. Ver 35-04-SUMMARY.md § Ação do Board.
    """
    pg = await get_pool()
    async with pg.acquire() as conn:
        projeto = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not projeto:
            raise HTTPException(404, "Projeto não encontrado")

    # Fase 35 / D-02: o SQL não mudou — só o pool. search_path=leadgen resolve o schema.
    lg = await get_lg_pool()
    async with lg.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT slug, keyword_principal, generated_at, competitor_count,
                      benchmark_word_count, required_sections, schema_missing,
                      geo_pages_benchmark, backlink_benchmark, trust_gaps, summary,
                      competitors_json, yaml_path, updated_at
               FROM competitor_audits
               WHERE projeto_id_uuid = $1""",
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
