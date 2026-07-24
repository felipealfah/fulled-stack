"""REQ-8-07 — POST /projetos/{uuid}/rank-tracking/bulk.

Grava DIRETO em leadgen_silver.rank_tracking no BigQuery via SA leadgen-sc.
Zero Postgres (D-07). BQ client mockado nos testes para não depender de
credenciais reais no CI.

Pré-condições:
- Túnel VPS Postgres em localhost:5434 (para _resolve_projeto).
- AUTH_ENABLED=false.

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_rank_tracking_bulk.py -v
"""

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from main import app  # noqa: E402
import db as db_module  # noqa: E402


# MM Entulho — id_int_legado=8 (verificado em 2026-07-24 via psql VPS)
PROJETO_MM_UUID = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"
PROJETO_MM_INT = 8


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    if db_module._pool is not None:
        try:
            await db_module._pool.close()
        except Exception:
            pass
        db_module._pool = None
    yield
    if db_module._pool is not None:
        try:
            await db_module._pool.close()
        except Exception:
            pass
        db_module._pool = None


@pytest.fixture
def mock_bq(monkeypatch):
    """Mock do _get_bq_client() — retorna client fake que aceita insert_rows_json."""
    mock_client = MagicMock()
    mock_client.insert_rows_json = MagicMock(return_value=[])  # sem erros BQ

    from routers import rank_tracking
    # Também limpa o singleton para não vazar entre testes
    rank_tracking._bq_client = None
    monkeypatch.setattr(rank_tracking, "_get_bq_client", lambda: mock_client)
    return mock_client


@pytest.mark.asyncio
async def test_rank_bulk_happy(mock_bq):
    """T1: 3 items válidos → 200 com inserted=3, chama BQ uma vez."""
    payload = {"items": [
        {"keyword": "kw1", "position": 3, "url": "https://x.com/a", "serp_date": "2026-07-24", "source": "serpapi"},
        {"keyword": "kw2", "position": None, "url": None, "serp_date": "2026-07-24", "source": "serpapi"},
        {"keyword": "kw3", "position": 15, "url": "https://x.com/b", "serp_date": "2026-07-24"},  # source default
    ]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 3
    assert body["errors"] == []
    mock_bq.insert_rows_json.assert_called_once()
    call_rows = mock_bq.insert_rows_json.call_args[0][1]
    assert len(call_rows) == 3
    # Confere schema BQ correto (projeto_id INT legado, projeto_nome preenchido, coletado_em ISO)
    assert call_rows[0]["projeto_id"] == PROJETO_MM_INT
    assert call_rows[0]["projeto_nome"] == "MM Entulho"
    assert call_rows[0]["keyword"] == "kw1"
    assert call_rows[0]["serp_position"] == 3
    assert call_rows[0]["target_url"] == "https://x.com/a"
    assert call_rows[0]["coletado_em"] == "2026-07-24"


@pytest.mark.asyncio
async def test_rank_bulk_empty(mock_bq):
    """T2: {items: []} → 200 sem chamar BQ."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json={"items": []})
    assert r.status_code == 200
    assert r.json() == {"inserted": 0, "errors": []}
    mock_bq.insert_rows_json.assert_not_called()


@pytest.mark.asyncio
async def test_rank_bulk_projeto_404(mock_bq):
    """T3: UUID inexistente → 404 pt-BR."""
    fake = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{fake}/rank-tracking/bulk", json={"items": [
            {"keyword": "x", "serp_date": "2026-07-24"},
        ]})
    assert r.status_code == 404
    assert "Projeto" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rank_bulk_too_many_items(mock_bq):
    """T4 (CRIT-9): >500 items → 413."""
    items = [{"keyword": f"k{i}", "serp_date": "2026-07-24"} for i in range(501)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json={"items": items})
    assert r.status_code == 413
    assert "500" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rank_bulk_no_bq_credentials(monkeypatch):
    """T5: GCP_SC_KEY ausente → 500 com mensagem clara pt-BR."""
    from routers import rank_tracking
    rank_tracking._bq_client = None
    monkeypatch.setattr(rank_tracking, "_get_bq_client", lambda: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json={"items": [
            {"keyword": "x", "serp_date": "2026-07-24"},
        ]})
    assert r.status_code == 500
    assert "GCP_SC_KEY" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rank_bulk_bq_errors_surfaced(monkeypatch):
    """T6: BQ insert retorna errors → 200 com errors[], sem 500 (best-effort)."""
    mock_client = MagicMock()
    mock_client.insert_rows_json = MagicMock(return_value=[
        {"index": 0, "errors": [{"reason": "invalid", "message": "bad row"}]},
    ])
    from routers import rank_tracking
    rank_tracking._bq_client = None
    monkeypatch.setattr(rank_tracking, "_get_bq_client", lambda: mock_client)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json={"items": [
            {"keyword": "x", "serp_date": "2026-07-24"},
        ]})
    assert r.status_code == 200
    body = r.json()
    assert body["inserted"] == 0
    assert len(body["errors"]) >= 1


@pytest.mark.asyncio
async def test_rank_bulk_source_ignored_but_accepted(mock_bq):
    """T7: source no payload é aceito (pydantic OK) mas dropado do BQ row.

    O schema real de leadgen_silver.rank_tracking (bq_client.py:62-73) NÃO tem
    coluna 'source'. Enviar iria quebrar o insert. O router aceita mas descarta.
    """
    payload = {"items": [
        {"keyword": "kw1", "serp_date": "2026-07-24", "source": "serpapi"},
    ]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json=payload)
    assert r.status_code == 200
    call_rows = mock_bq.insert_rows_json.call_args[0][1]
    assert "source" not in call_rows[0]


@pytest.mark.asyncio
async def test_rank_bulk_invalid_serp_date(mock_bq):
    """T8: serp_date malformado → 422 do Pydantic (não é error accumulation)."""
    payload = {"items": [
        {"keyword": "kw1", "serp_date": "not-a-date"},
    ]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/projetos/{PROJETO_MM_UUID}/rank-tracking/bulk", json=payload)
    assert r.status_code == 422
