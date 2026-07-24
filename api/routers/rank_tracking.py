"""REQ-8-07 — POST /projetos/{projeto_id}/rank-tracking/bulk.

Grava DIRETO em leadgen_silver.rank_tracking no BigQuery via SA leadgen-sc.
ZERO Postgres — decisão D-07: rank_tracking não é tabela do Postgres, dados vivem no BQ.

Schema BQ (cross-check com Full_AIOS_LEADGEN/worker/scripts/bq_client.py:62-73):
  projeto_id    INT64   NOT NULL
  projeto_nome  STRING  NOT NULL
  keyword       STRING  NOT NULL
  kw_type       STRING
  papel         STRING
  target_url    STRING       ← recebe `url` do payload
  serp_position INT64        ← recebe `position` do payload
  coletado_em   DATE    NOT NULL   ← recebe `serp_date` do payload

Nota: o campo `source` do payload é ACEITO (compat com skills) mas NÃO gravado
no BQ (coluna não existe). Se schema BQ evoluir para incluir source/url textual,
adicionar as colunas ao dict rows aqui.

Autenticação com BQ via GCP_SC_KEY no env do container fastapi.
Auth HTTP via middleware — decisão D-09.
"""

import json
import os
import sys
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from google.cloud import bigquery
from google.oauth2 import service_account
from pydantic import BaseModel

from db import get_pool
from routers._common import _resolve_projeto

router = APIRouter(prefix="/projetos", tags=["rank-tracking"])

_BQ_PROJECT = "gifted-slice-357413"
_BQ_SILVER_RANK = f"{_BQ_PROJECT}.leadgen_silver.rank_tracking"
_BQ_SCOPES = ["https://www.googleapis.com/auth/bigquery"]
_bq_client: bigquery.Client | None = None

MAX_ITEMS = 500


def _get_bq_client() -> bigquery.Client | None:
    """Retorna singleton BQ client ou None se GCP_SC_KEY não configurada.

    Padrão idêntico ao review.py — replicado aqui para isolamento do router.
    """
    global _bq_client
    if _bq_client is not None:
        return _bq_client
    gcp_key_json = os.environ.get("GCP_SC_KEY")
    if not gcp_key_json:
        print("[WARN] GCP_SC_KEY não configurada — rank_tracking BQ writes desabilitados", file=sys.stderr)
        return None
    try:
        key_info = json.loads(gcp_key_json)
        credentials = service_account.Credentials.from_service_account_info(
            key_info, scopes=_BQ_SCOPES
        )
        _bq_client = bigquery.Client(project=_BQ_PROJECT, credentials=credentials)
        return _bq_client
    except Exception as e:
        print(f"[WARN] Erro inicializando BQ client rank_tracking: {e}", file=sys.stderr)
        return None


class RankTrackingItem(BaseModel):
    keyword: str
    position: int | None = None
    url: str | None = None
    serp_date: date
    source: str = "serpapi"  # aceito, mas não gravado no BQ (schema não tem coluna)


class RankTrackingBulkRequest(BaseModel):
    items: list[RankTrackingItem]


@router.post("/{projeto_id}/rank-tracking/bulk")
async def bulk_insert_rank_tracking(projeto_id: str, body: RankTrackingBulkRequest):
    """Bulk INSERT em leadgen_silver.rank_tracking (BigQuery).

    - Até 500 items por request (CRIT-9) — mais que isso retorna 413.
    - Best-effort BQ: se insert_rows_json retornar errors, resposta é 200 com
      errors[] no body (nunca 500 — skill decide o que fazer).
    - GCP_SC_KEY ausente = 500 pt-BR explícito.
    """
    if len(body.items) > MAX_ITEMS:
        raise HTTPException(413, f"Máximo {MAX_ITEMS} items por request")

    pool = await get_pool()
    async with pool.acquire() as conn:
        proj = await _resolve_projeto(conn, projeto_id)
        # Precisamos de projeto_nome (NOT NULL no BQ) — fetch adicional
        proj_row = await conn.fetchrow(
            "SELECT projeto_nome FROM projetos WHERE id = $1::uuid",
            projeto_id,
        )
        projeto_nome = proj_row["projeto_nome"] if proj_row else str(proj["id"])
        pid_int = proj["id_int_legado"]

    if not body.items:
        return {"inserted": 0, "errors": []}

    bq = _get_bq_client()
    if bq is None:
        raise HTTPException(500, "GCP_SC_KEY não configurada — impossível gravar no BigQuery")

    if pid_int is None:
        # Schema BQ exige projeto_id INT NOT NULL. Sem id_int_legado, não grava.
        raise HTTPException(
            500,
            "Projeto sem id_int_legado — impossível gravar em leadgen_silver.rank_tracking (INT64 NOT NULL)",
        )

    # Monta rows compatíveis com schema real de leadgen_silver.rank_tracking
    # (bq_client.py:62-73 — projeto_id, projeto_nome, keyword, kw_type, papel,
    # target_url, serp_position, coletado_em). O campo `source` do payload é
    # descartado (não existe no schema).
    rows: list[dict[str, Any]] = []
    for item in body.items:
        rows.append({
            "projeto_id": pid_int,
            "projeto_nome": projeto_nome,
            "keyword": item.keyword,
            "kw_type": None,
            "papel": None,
            "target_url": item.url,
            "serp_position": item.position,
            "coletado_em": item.serp_date.isoformat(),
        })

    errors = bq.insert_rows_json(_BQ_SILVER_RANK, rows)
    if errors:
        # Best-effort: não levanta 500. Retorna 200 com errors[] pra skill decidir.
        return {"inserted": 0, "errors": errors}

    return {"inserted": len(rows), "errors": []}
