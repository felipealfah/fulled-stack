"""ranking.py — GET /projetos/{id}/ranking

Le ranking_dashboard_cache e ranking_history_cache do Postgres local.
Phase 03: migrado de DuckDB/Parquet para BQ.
2026-07-23: migrado de BQ live para cache Postgres — o workflow n8n
"[LEADGEN] Sync Gold → Postgres" (05:00) puxa o gold do BQ 1x/dia e grava
nas tabelas *_cache. A API não consulta mais o BigQuery.
Ver ADR 2026-07-23_Ranking_Cache_Postgres_n8n (Full_AIOS_LEADGEN).

Se dados nao existirem no cache (sync ainda nao rodou): {"status": "not_ready", ...}
Se projeto nao existir: 404
"""

import re
import unicodedata
from pathlib import Path
from typing import Optional

import asyncpg
import pandas as pd
from fastapi import APIRouter, HTTPException

from db import get_pool

router = APIRouter(prefix="/projetos", tags=["ranking"])

DATA_DIR = Path("/data/leadgen")

_NOT_READY_MSG = (
    "Ranking ainda não sincronizado. O sync n8n (BQ → Postgres) roda diariamente "
    "às 05:00 — ou execute o workflow '[LEADGEN] Sync Gold → Postgres' manualmente."
)


def _slugify(name: str) -> str:
    """Normaliza projeto_nome -> slug. DEVE ser identica a utils.slugify().

    Copia intencional para evitar dependencia de modulo externo no container FastAPI.
    Se alterar utils.py, alterar aqui tambem.

    'Marido de Aluguel' -> 'marido_de_aluguel'
    """
    text = "".join(
        c for c in unicodedata.normalize("NFD", name.lower().strip())
        if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _compute_report(history_rows: list[dict], projeto_id_int: int, projeto_nome: str) -> dict:
    """Calcula relatório de ranking comparando último snapshot vs penúltimo.

    Lê de ranking_history_cache (Postgres) — recebe as rows já consultadas.

    Modos:
    - baseline: apenas 1 snapshot_date distinto → deltas null
    - weekly: 2+ snapshots → deltas calculados

    Retorna dict pronto para serialização JSON (sem NaN — substituídos por None).
    """
    if not history_rows:
        return {"status": "not_ready", "message": "Histórico ainda não disponível."}

    df = pd.DataFrame(history_rows)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date

    snapshot_dates = sorted(df["snapshot_date"].unique(), reverse=True)
    curr_date = snapshot_dates[0]
    prev_date = snapshot_dates[1] if len(snapshot_dates) >= 2 else None
    mode = "weekly" if prev_date is not None else "baseline"

    curr_df = df[df["snapshot_date"] == curr_date].copy()
    prev_df = df[df["snapshot_date"] == prev_date].copy() if prev_date else None

    def _safe(v):
        if v != v:  # NaN check
            return None
        return v

    def _safe_int(v):
        s = _safe(v)
        return int(s) if s is not None else None

    def _count(status_val: str) -> int:
        return int((curr_df["status"] == status_val).sum())

    total = len(curr_df)
    rankeando = _count("RANKEANDO")
    gap = _count("GAP")
    surpresa = _count("SURPRESA")

    rankeando_delta = None
    gap_delta = None
    surpresa_delta = None

    if prev_df is not None:
        prev_rankeando = int((prev_df["status"] == "RANKEANDO").sum())
        prev_gap = int((prev_df["status"] == "GAP").sum())
        prev_surpresa = int((prev_df["status"] == "SURPRESA").sum())
        rankeando_delta = rankeando - prev_rankeando
        gap_delta = gap - prev_gap
        surpresa_delta = surpresa - prev_surpresa

    top_df = curr_df[curr_df["status"] == "RANKEANDO"].sort_values("serp_position")
    top_rankeando = [
        {
            "keyword": r["keyword"],
            "serp_position": _safe_int(r["serp_position"]),
            "sc_position": _safe(r.get("sc_position_avg_30d")),
            "sc_impressions_30d": _safe_int(r.get("sc_impressions_30d")),
        }
        for _, r in top_df.head(10).iterrows()
    ]

    fell = []
    rose = []
    new_surpresa = []

    if prev_df is not None:
        merged = curr_df.merge(
            prev_df[["keyword", "serp_position", "status"]].rename(
                columns={"serp_position": "serp_position_prev", "status": "status_prev"}
            ),
            on="keyword",
            how="left",
        )

        fell_df = merged.dropna(subset=["serp_position_prev"]).copy()
        fell_df = fell_df[fell_df["serp_position"].notna()]
        fell_df["delta"] = fell_df["serp_position"] - fell_df["serp_position_prev"]
        fell_df = fell_df[fell_df["delta"] >= 3].sort_values("delta", ascending=False)
        fell = [
            {
                "keyword": r["keyword"],
                "prev_serp": _safe_int(r["serp_position_prev"]),
                "curr_serp": _safe_int(r["serp_position"]),
                "delta": int(r["delta"]),
            }
            for _, r in fell_df.iterrows()
        ]

        rose_df = merged.dropna(subset=["serp_position_prev"]).copy()
        rose_df = rose_df[rose_df["serp_position"].notna()]
        rose_df["delta"] = rose_df["serp_position"] - rose_df["serp_position_prev"]
        rose_df = rose_df[rose_df["delta"] <= -3].sort_values("delta")
        rose = [
            {
                "keyword": r["keyword"],
                "prev_serp": _safe_int(r["serp_position_prev"]),
                "curr_serp": _safe_int(r["serp_position"]),
                "delta": int(r["delta"]),
            }
            for _, r in rose_df.iterrows()
        ]

        prev_keywords = set(prev_df["keyword"].tolist())
        curr_surpresa = curr_df[curr_df["status"] == "SURPRESA"]
        new_surpresa = [
            {
                "keyword": r["keyword"],
                "sc_impressions_30d": _safe_int(r.get("sc_impressions_30d")),
            }
            for _, r in curr_surpresa.iterrows()
            if r["keyword"] not in prev_keywords
            or prev_df[prev_df["keyword"] == r["keyword"]]["status"].values[0] != "SURPRESA"
        ]

    crit_df = curr_df[
        (curr_df["status"] != "RANKEANDO")
        & (curr_df["sc_impressions_30d"].notna())
        & (curr_df["sc_impressions_30d"] > 50)
    ].sort_values("sc_impressions_30d", ascending=False)
    critical_gaps = [
        {
            "keyword": r["keyword"],
            "status": r["status"],
            "sc_impressions_30d": _safe_int(r["sc_impressions_30d"]),
            "sc_position": _safe(r.get("sc_position_avg_30d")),
        }
        for _, r in crit_df.iterrows()
    ]

    return {
        "status": "ok",
        "mode": mode,
        "report_date": curr_date.isoformat(),
        "current_snapshot_date": curr_date.isoformat(),
        "previous_snapshot_date": prev_date.isoformat() if prev_date else None,
        "projeto_id": projeto_id_int,
        "projeto_nome": projeto_nome,
        "summary": {
            "total": total,
            "rankeando": rankeando,
            "rankeando_delta": rankeando_delta,
            "gap": gap,
            "gap_delta": gap_delta,
            "surpresa": surpresa,
            "surpresa_delta": surpresa_delta,
        },
        "top_rankeando": top_rankeando,
        "fell": fell,
        "rose": rose,
        "new_surpresa": new_surpresa,
        "critical_gaps": critical_gaps,
    }


@router.get("/{projeto_id}/ranking")
async def get_ranking(projeto_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT projeto_nome, id_int_legado, metadata->>'dominio' AS dominio FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    projeto_id_int = row["id_int_legado"]

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM ranking_dashboard_cache
                WHERE projeto_id = $1
                ORDER BY status, serp_position NULLS LAST
                """,
                projeto_id_int,
            )
    except asyncpg.UndefinedTableError:
        return {"status": "not_ready", "message": _NOT_READY_MSG}

    if not rows:
        return {
            "status": "not_ready",
            "message": "Ranking ainda não processado para este projeto. Execute o agente rank_intel.",
        }

    updated_at = None
    keywords = []
    for r in rows:
        kw = dict(r)
        synced = kw.pop("synced_at", None)
        if synced is not None and (updated_at is None or synced > updated_at):
            updated_at = synced
        for k, v in kw.items():
            if hasattr(v, "isoformat"):
                kw[k] = v.isoformat()
        keywords.append(kw)

    return {
        "status": "ok",
        "projeto_id": projeto_id,
        "projeto_nome": row["projeto_nome"],
        "dominio": row["dominio"],
        "total": len(keywords),
        "keywords": keywords,
        # última sincronização BQ → Postgres (não mais "agora")
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
    }


@router.get("/{projeto_id}/ranking/history")
async def get_ranking_history(projeto_id: str, keyword: Optional[str] = None):
    """Retorna série histórica de posições por keyword.

    Query param opcional: keyword=<texto> — filtra para uma única keyword.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT projeto_nome, id_int_legado FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    projeto_id_int = row["id_int_legado"]

    try:
        async with pool.acquire() as conn:
            if keyword:
                rows = await conn.fetch(
                    """
                    SELECT keyword, snapshot_date, serp_position, sc_position_avg_30d
                    FROM ranking_history_cache
                    WHERE projeto_id = $1 AND keyword = $2
                    ORDER BY keyword, snapshot_date
                    """,
                    projeto_id_int,
                    keyword,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT keyword, snapshot_date, serp_position, sc_position_avg_30d
                    FROM ranking_history_cache
                    WHERE projeto_id = $1
                    ORDER BY keyword, snapshot_date
                    """,
                    projeto_id_int,
                )
    except asyncpg.UndefinedTableError:
        return {"status": "not_ready", "message": _NOT_READY_MSG}

    if not rows:
        return {
            "status": "not_ready",
            "message": "Histórico ainda não disponível. Execute o pipeline rank_intel ao menos uma vez.",
        }

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        kw = r["keyword"]
        if kw not in grouped:
            grouped[kw] = []
        serp = r["serp_position"]
        sc = r["sc_position_avg_30d"]
        snap = r["snapshot_date"]
        grouped[kw].append({
            "date": snap.isoformat() if hasattr(snap, "isoformat") else str(snap),
            "serp_position": None if serp is None else int(serp),
            "sc_position": None if sc is None else round(float(sc), 1),
        })

    return {
        "status": "ok",
        "projeto_id": projeto_id,
        "keywords": [{"keyword": kw, "series": series} for kw, series in grouped.items()],
    }


@router.get("/{projeto_id}/ranking/report")
async def get_ranking_report(projeto_id: str):
    """Relatório semanal de ranking: sumário atual + deltas vs snapshot anterior.

    Modos:
    - not_ready: histórico BQ vazio (rank_intel ainda não rodou)
    - baseline: apenas 1 snapshot_date → sem deltas
    - weekly: 2+ snapshots → deltas calculados
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT projeto_nome, id_int_legado FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    projeto_id_int = row["id_int_legado"]

    try:
        async with pool.acquire() as conn:
            hist_rows = await conn.fetch(
                """
                SELECT keyword, snapshot_date, serp_position,
                       sc_position_avg_30d, sc_impressions_30d, status
                FROM ranking_history_cache
                WHERE projeto_id = $1
                ORDER BY snapshot_date
                """,
                projeto_id_int,
            )
    except asyncpg.UndefinedTableError:
        return {"status": "not_ready", "message": _NOT_READY_MSG}

    if not hist_rows:
        return {
            "status": "not_ready",
            "message": "Histórico de ranking ainda não disponível. Execute rank_intel ao menos uma vez.",
        }
    return _compute_report([dict(r) for r in hist_rows], projeto_id_int, row["projeto_nome"])


@router.get("/{projeto_id}/seo-yaml-template")
async def get_seo_yaml_template(projeto_id: str):
    """Gera YAML de input para o agente seo_architect.

    Serviços: derivados dos nichos das pesquisas aprovadas no Gate 2 vinculadas ao projeto.
    Cidades:  derivadas do metadata do projeto (campo 'cidade').
    Retorna string YAML + estrutura JSON com os mesmos dados.
    """
    import re as _re
    import unicodedata as _ud

    def _url_slug(text: str) -> str:
        t = "".join(
            c for c in _ud.normalize("NFD", text.lower().strip())
            if _ud.category(c) != "Mn"
        )
        t = _re.sub(r"[^\w\s-]", "", t)
        t = _re.sub(r"[\s_]+", "-", t)
        return t.strip("-")

    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow(
            "SELECT projeto_nome, metadata->>'cidade' AS cidade_meta FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not proj:
            raise HTTPException(404, "Projeto não encontrado")

        pesquisas = await conn.fetch(
            """
            SELECT DISTINCT nicho
            FROM pesquisas
            WHERE projeto_id = $1
              AND status IN ('gate_2_approved', 'gate_2_pending', 'approved')
              AND nicho IS NOT NULL AND nicho != ''
            ORDER BY nicho
            """,
            projeto_id,
        )

    slug = _slugify(proj["projeto_nome"])

    servicos = [
        {"slug": _url_slug(p["nicho"]), "nome": p["nicho"].title()}
        for p in pesquisas
    ]

    cidade_raw = proj["cidade_meta"] or ""
    cidades = [c.strip() for c in cidade_raw.replace(";", ",").split(",") if c.strip()] or ["Brasília"]

    servicos_yaml = "\n".join(
        f"  - nome: {s['nome']}\n    slug: {s['slug']}" for s in servicos
    ) or "  # nenhuma pesquisa Gate 2 vinculada a este projeto"
    cidades_yaml = "\n".join(f"  - {c}" for c in cidades)

    yaml_str = (
        f"projeto_id: {projeto_id}\n"
        f"slug: {slug}\n"
        f"servicos:\n{servicos_yaml}\n"
        f"cidades:\n{cidades_yaml}\n"
    )

    return {
        "yaml": yaml_str,
        "slug": slug,
        "servicos": servicos,
        "cidades": cidades,
    }


@router.post("/{projeto_id}/rank-intel")
async def trigger_rank_intel(projeto_id: str):
    """Escreve arquivo trigger em /data/leadgen/.trigger_{id_int}.
    O sc-sync detecta o arquivo no próximo ciclo (≤60s) e executa o pipeline completo.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id_int_legado FROM projetos WHERE id = $1", projeto_id
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    projeto_id_int = row["id_int_legado"]
    trigger_path = DATA_DIR / f".trigger_{projeto_id_int}"
    trigger_path.touch()
    print(f"[rank_intel] trigger criado: {trigger_path}", flush=True)

    return {"status": "queued", "message": "Pipeline rank_intel enfileirado. Resultado disponível em até 60s."}
