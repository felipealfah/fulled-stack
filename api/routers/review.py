import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from google.cloud import bigquery
from google.oauth2 import service_account
from pydantic import BaseModel
from db import get_pool

router = APIRouter(prefix="/pesquisas", tags=["review"])

_BQ_PROJECT = "gifted-slice-357413"
_BQ_SILVER_KW_PLAN = f"{_BQ_PROJECT}.leadgen_silver.kw_plan"
_BQ_GOLD_KW_PLAN = f"{_BQ_PROJECT}.leadgen_gold.kw_plan"
_BQ_SCOPES = ["https://www.googleapis.com/auth/bigquery"]
_bq_client: bigquery.Client | None = None


def _get_bq_client() -> bigquery.Client | None:
    """Retorna singleton BQ client ou None se GCP_SC_KEY não configurada."""
    global _bq_client
    if _bq_client is not None:
        return _bq_client
    gcp_key_json = os.environ.get("GCP_SC_KEY")
    if not gcp_key_json:
        print("[WARN] GCP_SC_KEY não configurada — BQ writes desabilitados", file=sys.stderr)
        return None
    try:
        key_info = json.loads(gcp_key_json)
        credentials = service_account.Credentials.from_service_account_info(
            key_info, scopes=_BQ_SCOPES
        )
        _bq_client = bigquery.Client(project=_BQ_PROJECT, credentials=credentials)
        return _bq_client
    except Exception as e:
        print(f"[WARN] Erro inicializando BQ client: {e}", file=sys.stderr)
        return None


def _insert_kw_plan_silver(client: bigquery.Client, rows: list[dict]) -> None:
    """INSERT síncrono em leadgen_silver.kw_plan — chamado via run_in_executor."""
    errors = client.insert_rows_json(_BQ_SILVER_KW_PLAN, rows)
    if errors:
        print(f"[WARN] BQ kw_plan silver errors: {errors}", file=sys.stderr)
    else:
        print(f"[bq] INSERT {len(rows)} rows em {_BQ_SILVER_KW_PLAN}")


def _insert_kw_plan_gold(client: bigquery.Client, rows: list[dict]) -> None:
    """INSERT síncrono em leadgen_gold.kw_plan — chamado via run_in_executor."""
    errors = client.insert_rows_json(_BQ_GOLD_KW_PLAN, rows)
    if errors:
        print(f"[WARN] BQ kw_plan gold errors: {errors}", file=sys.stderr)
    else:
        print(f"[bq] INSERT {len(rows)} rows em {_BQ_GOLD_KW_PLAN}")


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    score: float | None = None
    go_nogo: str | None = None
    board_note: str | None = None
    status: str | None = None
    kw_type: str | None = None


class ApproveRequest(BaseModel):
    approved_keywords: list[str]  # textos das keywords aprovadas


class KeywordInput(BaseModel):
    keyword: str
    kw_type: str  # PAGINA_PRINCIPAL | SERVICO | PAGINA_GEO | SECAO | DESCARTA
    avg_monthly_searches: int | None = None
    bid_pos5_8_brl: float | None = None
    bid_pos1_4_brl: float | None = None
    competition_index: float | None = None
    competition: str | int | None = None
    board_note: str | None = None


class PesquisaCreate(BaseModel):
    projeto_nome: str
    nicho: str
    cidade: str = "Brasília"
    geo_target_id: str | None = None
    papel: str | None = None  # 'principal' | 'servico' | None
    projeto_id: str | None = None  # UUID do projeto (opcional)
    avaliacao_json: dict | None = None
    seed_keywords: list[str] | None = None
    keywords: list[KeywordInput] = []
    skip_descarta: bool = True  # não insere kw_staging com kw_type=DESCARTA


@router.post("/")
async def create_pesquisa(body: PesquisaCreate):
    """Cria pesquisa + kw_staging em uma única transação.

    Usado pelo agente `/kw-validator` para persistir o resultado do
    kw_research + classificação. A pesquisa nasce com status='classificado'
    (kw-validator já classificou — Gate 2 no dashboard /kw-planner) e as
    keywords com status='pending'.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pesquisa_row = await conn.fetchrow(
                """
                INSERT INTO pesquisas (
                    projeto_nome, nicho, cidade, geo_target_id, status,
                    papel, projeto_id_uuid, avaliacao_json, seed_keywords
                )
                VALUES ($1, $2, $3, $4, 'classificado', $5, $6::uuid, $7::jsonb, $8::jsonb)
                RETURNING *
                """,
                body.projeto_nome,
                body.nicho,
                body.cidade,
                body.geo_target_id,
                body.papel,
                body.projeto_id,
                json.dumps(body.avaliacao_json) if body.avaliacao_json is not None else None,
                json.dumps(body.seed_keywords) if body.seed_keywords is not None else None,
            )
            pesquisa_id = pesquisa_row["id"]

            kw_rows = [
                k for k in body.keywords
                if not (body.skip_descarta and k.kw_type == "DESCARTA")
            ]
            inserted = 0
            if kw_rows:
                values = []
                params: list = []
                for i, k in enumerate(kw_rows):
                    base = i * 9
                    values.append(
                        f"(${base+1}::uuid, ${base+2}, ${base+3}, ${base+4}, "
                        f"${base+5}, ${base+6}, ${base+7}, ${base+8}, ${base+9}, 'pending')"
                    )
                    params.extend([
                        pesquisa_id,
                        k.keyword,
                        k.kw_type,
                        k.avg_monthly_searches,
                        k.bid_pos5_8_brl,
                        k.bid_pos1_4_brl,
                        k.competition_index,
                        str(k.competition) if k.competition is not None else None,
                        k.board_note,
                    ])
                sql = (
                    "INSERT INTO kw_staging (pesquisa_id, keyword, kw_type, "
                    "avg_monthly_searches, bid_pos5_8_brl, bid_pos1_4_brl, "
                    "competition_index, competition, board_note, status) VALUES "
                    + ", ".join(values)
                )
                await conn.execute(sql, *params)
                inserted = len(kw_rows)

    return {
        "pesquisa": dict(pesquisa_row),
        "keywords_inseridas": inserted,
        "keywords_ignoradas_descarta": len(body.keywords) - inserted,
    }


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


@router.post("/{pesquisa_id}/auto-advance")
async def auto_advance_pesquisa(pesquisa_id: str):
    """Chamado pelo agente kw_research ao concluir — dispara kw_validator sem interação do Board."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        await conn.execute(
            "UPDATE pesquisas SET status = 'approved', reviewed_at = NOW() WHERE id = $1",
            pesquisa_id,
        )

        exec_id = await conn.fetchval(
            """INSERT INTO agent_executions
               (pesquisa_id, analysis_version, agent_name, status, started_at)
               VALUES ($1, 1, 'kw_validator', 'pending', NOW())
               RETURNING id""",
            pesquisa_id,
        )

    return {"ok": True, "agent_executions_id": str(exec_id)}


class ApproveGate2Request(BaseModel):
    projeto_id: str | None = None       # UUID — vincular a projeto existente
    criar_projeto: bool = False          # criar novo projeto a partir desta pesquisa


class PesquisaVincularUpdate(BaseModel):
    projeto_id: str | None = None      # UUID do projeto
    papel: str | None = None           # 'principal' | 'servico'
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

        # Criar novo projeto a partir da pesquisa (ou reusar se nome já existe)
        if body.criar_projeto and not projeto_id:
            nome = pesquisa["projeto_nome"] or pesquisa["nicho"]
            row = await conn.fetchrow(
                """INSERT INTO projetos (projeto_nome, nicho, cidade, status, pesquisa_id_atual)
                   VALUES ($1, $2, $3, 'research', $4)
                   ON CONFLICT (projeto_nome) DO UPDATE SET updated_at = NOW()
                   RETURNING id""",
                nome,
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

        # Atualizar pesquisa — status 'aprovado' é o valor válido no check constraint
        await conn.execute(
            """UPDATE pesquisas
               SET status = 'aprovado', reviewed_at = NOW(), projeto_id = $2
               WHERE id = $1""",
            pesquisa_id, projeto_id,
        )

    # Gravar keywords aprovadas em BQ leadgen_silver.kw_plan (espelho — Postgres é fonte de verdade)
    bq = _get_bq_client()
    if bq:
        async with pool.acquire() as conn2:
            kw_rows = await conn2.fetch(
                """
                SELECT
                    ks.keyword,
                    ks.avg_monthly_searches,
                    ks.competition,
                    ks.competition_index,
                    ks.cpc_low_brl,
                    ks.cpc_high_brl,
                    ks.score           AS opportunity_score,
                    ks.go_nogo         AS recomendacao,
                    ks.go_nogo         AS board_go_nogo,
                    ks.board_note,
                    ks.kw_type         AS tipo,
                    p.id::text         AS pesquisa_id,
                    p.nicho,
                    p.cidade,
                    p.geo_target_id,
                    p.created_at       AS pesquisado_em,
                    p.projeto_nome,
                    NULL::text         AS projeto_url
                FROM kw_staging ks
                JOIN pesquisas p ON p.id = ks.pesquisa_id
                WHERE ks.pesquisa_id = $1
                  AND UPPER(COALESCE(ks.kw_type, '')) != 'DESCARTA'
                """,
                pesquisa_id,
            )

        promovido_em = datetime.now(timezone.utc).isoformat()
        rows_bq = []
        for row in kw_rows:
            d = dict(row)
            rows_bq.append({
                "pesquisa_id":          d["pesquisa_id"],
                "nicho":                d["nicho"],
                "cidade":               d["cidade"],
                "geo_target_id":        d.get("geo_target_id"),
                "pesquisado_em":        d["pesquisado_em"].isoformat() if d.get("pesquisado_em") else None,
                "keyword":              d["keyword"],
                "avg_monthly_searches": d.get("avg_monthly_searches"),
                "competition":          d.get("competition"),
                "competition_index":    d.get("competition_index"),
                "cpc_low_brl":          float(d["cpc_low_brl"]) if d.get("cpc_low_brl") else None,
                "cpc_high_brl":         float(d["cpc_high_brl"]) if d.get("cpc_high_brl") else None,
                "opportunity_score":    float(d["opportunity_score"]) if d.get("opportunity_score") else None,
                "recomendacao":         d.get("recomendacao"),
                "tipo":                 d.get("tipo"),
                "board_go_nogo":        d.get("board_go_nogo"),
                "board_note":           d.get("board_note"),
                "projeto_nome":         d.get("projeto_nome"),
                "projeto_url":          d.get("projeto_url"),
                "monthly_volumes":      None,
                "promovido_em":         promovido_em,
            })

        if rows_bq:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: _insert_kw_plan_silver(bq, rows_bq),
                )
            except Exception as e:
                print(f"[WARN] Erro gravando BQ silver.kw_plan: {e}", file=sys.stderr)

    return {
        "ok": True,
        "pesquisa_id": pesquisa_id,
        "status": "aprovado",
        "projeto_id": projeto_id,
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

        if not any([body.projeto_id, body.papel, body.servico_slug]):
            raise HTTPException(400, "Nenhum campo para atualizar")

        # projeto_id chega como UUID — precisa atualizar as duas colunas:
        # projeto_id_uuid (UUID, lido por projetos.py) e projeto_id (int legado)
        if body.projeto_id:
            projeto = await conn.fetchrow(
                "SELECT id_int_legado FROM projetos WHERE id = $1", body.projeto_id
            )
            if not projeto:
                raise HTTPException(404, "Projeto não encontrado")
            await conn.execute(
                """UPDATE pesquisas
                   SET projeto_id_uuid = $2, projeto_id = $3
                   WHERE id = $1""",
                pesquisa_id, body.projeto_id, projeto["id_int_legado"],
            )

        # papel e servico_slug são atualizações simples de texto
        if body.papel or body.servico_slug:
            extra: dict = {}
            if body.papel:
                extra["papel"] = body.papel
            if body.servico_slug:
                extra["servico_slug"] = body.servico_slug
            set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(extra))
            await conn.execute(
                f"UPDATE pesquisas SET {set_clause} WHERE id = $1",
                pesquisa_id, *extra.values(),
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


@router.post("/{pesquisa_id}/promote-gold")
async def promote_gold(pesquisa_id: str):
    """Gate 2 do Board — promove keywords aprovadas para leadgen_gold.kw_plan.

    Requer que a pesquisa já esteja com status='aprovado' (Gate 1 concluído).
    Idealmente chamado após /competitive-intel ter enriquecido as keywords com
    competitive_score e difficulty_label.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        pesquisa = await conn.fetchrow(
            "SELECT * FROM pesquisas WHERE id = $1", pesquisa_id
        )
        if not pesquisa:
            raise HTTPException(404, "Pesquisa não encontrada")

        if pesquisa["status"] != "aprovado":
            raise HTTPException(
                400,
                f"Pesquisa não está com status 'aprovado' (status atual: {pesquisa['status']}) "
                "— realize o Gate 1 (approve-gate2) antes de promover para gold",
            )

        kw_rows = await conn.fetch(
            """
            SELECT
                ks.keyword,
                ks.avg_monthly_searches,
                ks.competition,
                ks.competition_index,
                ks.cpc_low_brl,
                ks.cpc_high_brl,
                ks.score            AS opportunity_score,
                ks.go_nogo          AS recomendacao,
                ks.kw_type          AS tipo,
                ks.competitive_score,
                ks.difficulty_label,
                ks.board_note,
                p.id::text          AS pesquisa_id,
                p.nicho,
                p.cidade,
                p.geo_target_id,
                p.projeto_nome,
                proj.metadata->>'dominio' AS projeto_url
            FROM kw_staging ks
            JOIN pesquisas p ON p.id = ks.pesquisa_id
            LEFT JOIN projetos proj ON proj.id = p.projeto_id
            WHERE ks.pesquisa_id = $1
              AND UPPER(COALESCE(ks.kw_type, '')) != 'DESCARTA'
              AND ks.go_nogo = 'GO'
            """,
            pesquisa_id,
        )

    aprovado_em = datetime.now(timezone.utc).isoformat()
    rows_bq = []
    for row in kw_rows:
        d = dict(row)
        rows_bq.append({
            "pesquisa_id":          d["pesquisa_id"],
            "nicho":                d["nicho"],
            "cidade":               d["cidade"],
            "geo_target_id":        d.get("geo_target_id"),
            "keyword":              d["keyword"],
            "avg_monthly_searches": d.get("avg_monthly_searches"),
            "competition":          d.get("competition"),
            "competition_index":    d.get("competition_index"),
            "cpc_low_brl":          float(d["cpc_low_brl"]) if d.get("cpc_low_brl") else None,
            "cpc_high_brl":         float(d["cpc_high_brl"]) if d.get("cpc_high_brl") else None,
            "opportunity_score":    float(d["opportunity_score"]) if d.get("opportunity_score") else None,
            "recomendacao":         d.get("recomendacao"),
            "tipo":                 d.get("tipo"),
            "competitive_score":    float(d["competitive_score"]) if d.get("competitive_score") else None,
            "difficulty_label":     d.get("difficulty_label"),
            "board_note":           d.get("board_note"),
            "projeto_nome":         d.get("projeto_nome"),
            "projeto_url":          d.get("projeto_url"),
            "gate2_status":         "go",
            "aprovado_em":          aprovado_em,
        })

    bq_status = "ok"
    bq = _get_bq_client()
    if bq and rows_bq:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: _insert_kw_plan_gold(bq, rows_bq),
            )
        except Exception as e:
            print(f"[WARN] Erro gravando BQ gold.kw_plan: {e}", file=sys.stderr)
            bq_status = "warn"
    elif not bq:
        bq_status = "warn"

    return {
        "ok": True,
        "pesquisa_id": pesquisa_id,
        "keywords_promovidas": len(rows_bq),
        "bq_status": bq_status,
    }


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
