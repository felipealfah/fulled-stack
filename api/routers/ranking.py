"""ranking.py — GET /projetos/{id}/ranking

Le ranking_gold_{slug}.parquet via DuckDB e retorna JSON com metricas de ranking.

Se arquivo nao existir: {"status": "not_ready", "message": "..."}
Se projeto nao existir: 404

Slug gerado a partir de projeto_nome usando a mesma logica de utils.py (D-06).
ATENCAO: se slugify() for alterado em utils.py, atualizar aqui tambem.
"""

import math
import re
import unicodedata
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException

from db import get_pool

router = APIRouter(prefix="/projetos", tags=["ranking"])

DATA_DIR = Path("/data/leadgen")


def _slugify(name: str) -> str:
    """Normaliza projeto_nome -> slug Parquet. DEVE ser identica a utils.slugify().

    Copia intencional para evitar dependencia de modulo externo no container FastAPI.
    Se alterar utils.py, alterar aqui tambem.

    'Marido de Aluguel' -> 'marido_de_aluguel'
    """
    # Remove acentos via NFD decomposition
    text = "".join(
        c for c in unicodedata.normalize("NFD", name.lower().strip())
        if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^\w\s]", "", text)        # remove punctuation
    text = re.sub(r"\s+", "_", text)            # spaces -> underscores
    text = re.sub(r"_+", "_", text).strip("_")  # collapse multiple _
    return text


def _compute_report(history_path: Path, projeto_id: int, projeto_nome: str) -> dict:
    """Calcula relatório de ranking comparando último snapshot vs penúltimo.

    Modos:
    - baseline: apenas 1 snapshot_date distinto → deltas null
    - weekly: 2+ snapshots → deltas calculados

    Retorna dict pronto para serialização JSON (sem NaN — substituídos por None).
    """
    from datetime import date

    df = pd.read_parquet(history_path)

    # Garante coluna snapshot_date como date (pode vir como Timestamp)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date

    # Snapshots distintos ordenados DESC (mais recente primeiro)
    snapshot_dates = sorted(df["snapshot_date"].unique(), reverse=True)
    curr_date = snapshot_dates[0]
    prev_date = snapshot_dates[1] if len(snapshot_dates) >= 2 else None
    mode = "weekly" if prev_date is not None else "baseline"

    curr_df = df[df["snapshot_date"] == curr_date].copy()
    prev_df = df[df["snapshot_date"] == prev_date].copy() if prev_date else None

    # Helper para NaN → None
    def _safe(v):
        if v != v:  # NaN check
            return None
        return v

    def _safe_int(v):
        s = _safe(v)
        return int(s) if s is not None else None

    # Contagens por status no snapshot atual
    def _count(status_val: str) -> int:
        return int((curr_df["status"] == status_val).sum())

    total = len(curr_df)
    rankeando = _count("RANKEANDO")
    gap = _count("GAP")
    surpresa = _count("SURPRESA")

    # Deltas (None em baseline)
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

    # top_rankeando: top 10 RANKEANDO por serp_position ASC
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

    # fell, rose, new_surpresa: apenas em modo weekly
    fell = []
    rose = []
    new_surpresa = []

    if prev_df is not None:
        # Merge pelo keyword para comparar posições
        merged = curr_df.merge(
            prev_df[["keyword", "serp_position", "status"]].rename(
                columns={"serp_position": "serp_position_prev", "status": "status_prev"}
            ),
            on="keyword",
            how="left",
        )

        # fell: serp_position piorou >= 3 (número maior = posição pior)
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

        # rose: serp_position melhorou >= 3 (número menor = posição melhor)
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

        # new_surpresa: status SURPRESA no curr que não existia no prev OU era diferente
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

    # critical_gaps: sc_impressions_30d > 50 AND status != RANKEANDO
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
        "projeto_id": projeto_id,
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
async def get_ranking(projeto_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT projeto_nome, metadata->>'dominio' AS dominio FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    slug = _slugify(row["projeto_nome"])
    gold_path = DATA_DIR / "gold" / f"ranking_gold_{slug}.parquet"

    if not gold_path.exists():
        return {
            "status": "not_ready",
            "message": "Ranking ainda não processado para este projeto. Aguarde o agente rank_intel.",
        }

    # DuckDB: fresh connection per request (in-memory, read-only Parquet)
    conn_duck = duckdb.connect()
    try:
        df = conn_duck.execute(
            "SELECT * FROM read_parquet(?) ORDER BY status, serp_position NULLS LAST",
            [str(gold_path)],
        ).df()
    finally:
        conn_duck.close()

    keywords = df.to_dict(orient="records")

    # Substitui NaN (pandas) por None para serialização JSON correta
    for kw in keywords:
        for k, v in kw.items():
            if v != v:  # NaN check: NaN != NaN é True em Python
                kw[k] = None

    from datetime import datetime, timezone
    updated_at = datetime.fromtimestamp(gold_path.stat().st_mtime, tz=timezone.utc).isoformat()

    return {
        "status": "ok",
        "projeto_id": projeto_id,
        "projeto_nome": row["projeto_nome"],
        "dominio": row["dominio"],
        "total": len(keywords),
        "keywords": keywords,
        "updated_at": updated_at,
    }


@router.get("/{projeto_id}/ranking/history")
async def get_ranking_history(projeto_id: int, keyword: Optional[str] = None):
    """Retorna série histórica de posições por keyword.

    Query param opcional: keyword=<texto> — filtra para uma única keyword.
    Lê ranking_history_{slug}.parquet via DuckDB e agrupa por keyword → series.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT projeto_nome FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    slug = _slugify(row["projeto_nome"])
    history_path = DATA_DIR / "gold" / f"ranking_history_{slug}.parquet"

    if not history_path.exists():
        return {
            "status": "not_ready",
            "message": "Histórico ainda não disponível. Execute o pipeline rank_intel ao menos uma vez.",
        }

    conn_duck = duckdb.connect()
    try:
        if keyword:
            df = conn_duck.execute(
                """
                SELECT keyword, snapshot_date, serp_position, sc_position_avg_30d
                FROM read_parquet(?)
                WHERE keyword = ?
                ORDER BY keyword, snapshot_date
                """,
                [str(history_path), keyword],
            ).df()
        else:
            df = conn_duck.execute(
                """
                SELECT keyword, snapshot_date, serp_position, sc_position_avg_30d
                FROM read_parquet(?)
                ORDER BY keyword, snapshot_date
                """,
                [str(history_path)],
            ).df()
    finally:
        conn_duck.close()

    # Agrupa por keyword → series
    grouped: dict[str, list[dict]] = {}
    for _, r in df.iterrows():
        kw = r["keyword"]
        if kw not in grouped:
            grouped[kw] = []
        serp = r["serp_position"]
        sc = r["sc_position_avg_30d"]
        grouped[kw].append({
            "date": str(r["snapshot_date"]),
            "serp_position": None if (serp != serp or serp is None) else int(serp),
            "sc_position": None if (sc != sc or sc is None) else round(float(sc), 1),
        })

    keywords_out = [
        {"keyword": kw, "series": series}
        for kw, series in grouped.items()
    ]

    return {
        "status": "ok",
        "projeto_id": projeto_id,
        "keywords": keywords_out,
    }


@router.get("/{projeto_id}/ranking/report")
async def get_ranking_report(projeto_id: int):
    """Relatório semanal de ranking: sumário atual + deltas vs snapshot anterior.

    Modos:
    - not_ready: history parquet não existe (Phase 17 ainda não rodou)
    - baseline: apenas 1 snapshot_date → sem deltas
    - weekly: 2+ snapshots → deltas calculados
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT projeto_nome FROM projetos WHERE id = $1",
            projeto_id,
        )
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    slug = _slugify(row["projeto_nome"])
    history_path = DATA_DIR / "gold" / f"ranking_history_{slug}.parquet"

    if not history_path.exists():
        return {
            "status": "not_ready",
            "message": "Histórico de ranking ainda não disponível para este projeto. "
                       "Aguarde o agente rank_intel gerar ao menos um snapshot.",
        }

    return _compute_report(history_path, projeto_id, row["projeto_nome"])


@router.get("/{projeto_id}/seo-yaml-template")
async def get_seo_yaml_template(projeto_id: int):
    """Gera YAML pronto para colar no Multica ao abrir issue do seo_architect.

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

        # Pesquisas aprovadas vinculadas ao projeto → fonte dos serviços (Gate 2)
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

    # Cidades: parse do campo metadata (pode ser "Brasília, DF" ou "Brasília")
    cidade_raw = proj["cidade_meta"] or ""
    cidades = [c.strip() for c in cidade_raw.replace(";", ",").split(",") if c.strip()] or ["Brasília"]

    # Monta YAML
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
async def trigger_rank_intel(projeto_id: int):
    """Escreve arquivo trigger em /data/leadgen/.trigger_{id}.
    O sc-sync detecta o arquivo no próximo ciclo (≤60s) e executa o pipeline completo.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM projetos WHERE id = $1", projeto_id)
        if not row:
            raise HTTPException(404, "Projeto não encontrado")

    trigger_path = DATA_DIR / f".trigger_{projeto_id}"
    trigger_path.touch()
    print(f"[rank_intel] trigger criado: {trigger_path}", flush=True)

    return {"status": "queued", "message": "Pipeline rank_intel enfileirado. Resultado disponível em até 60s."}
