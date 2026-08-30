"""Fase 35 / D-02 — rede de segurança dos routers de 2 passos.

Cobre `ranking.py`, `overrides.py` e `geo_targets.py`, os três routers cujas tabelas
(`ranking_dashboard_cache`, `ranking_history_cache`, `rank_intel_overrides`,
`projeto_geo_targets`) migram para o schema `leadgen` no Supabase.
ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Até este arquivo, nenhum dos três routers tinha teste automatizado — a migração
aconteceria às cegas. O contrato verificado aqui é o mesmo antes e depois da troca de
pool: o projeto é resolvido no Postgres da Stack (`projetos`, camada de decisão) e só
depois a tabela migrada é consultada no Supabase.

## Estado encontrado (pré-migração, medido em 2026-08-30)

`ranking.py` já falava UUID e respondia 200. `overrides.py` e `geo_targets.py` ainda
declaravam `projeto_id: int` e estavam órfãos da migração UUID da Phase 05 — o mesmo
bug que a Phase 12-02 corrigiu em `content.py`:

    GET /projetos/{uuid}/ranking/overrides  -> 422 (int_parsing)
    GET /projetos/8/ranking/overrides       -> 200  (nenhum cliente manda int)
    GET /projetos/{uuid}/geo-targets        -> 422 (int_parsing)
    GET /projetos/8/geo-targets             -> 500  (DataError: int vs coluna uuid)

O frontend (`ProjetoRanking.tsx`, `SeoPlan.tsx`) sempre manda o UUID da rota. Estes
testes descrevem o contrato correto — o que o cliente real exercita —, não o estado
quebrado. Ver "Desvios do plano" em 35-03-SUMMARY.md.

Pré-condições:
- Túnel VPS Postgres aberto em localhost:5433 (`bash vps_tunnel.sh -d`).
- LEADGEN_DB_URL configurada (vem do .env via conftest.py).
- AUTH_ENABLED=false (setado no conftest.py).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_routers_dois_passos.py -v
"""

import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from main import app  # noqa: E402
import db as db_module  # noqa: E402

# UUID real do projeto MM Entulho no VPS (id_int_legado=8).
PROJETO_MM_UUID = "f131ca75-1d73-4e04-a89b-3bb85045a9eb"
PROJETO_MM_INT = 8

# Marcador único dos registros criados aqui — o teardown apaga por ele.
KEYWORD_TESTE = "teste-fase35-dois-passos"
GEO_NOME_TESTE = "Teste Fase 35 Dois Passos"

# Chaves de topo medidas contra o código pré-migração (baseline SC-01).
CHAVES_RANKING = {
    "status", "projeto_id", "projeto_nome", "dominio", "total", "keywords", "updated_at",
}
CHAVES_HISTORY = {"status", "projeto_id", "keywords"}


@pytest.fixture(autouse=True)
async def _reset_pool_por_teste():
    """Zera `db._pool`. O `_lg_pool` do Supabase é zerado pelo conftest."""
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
async def lg_conn():
    """Conexão direta ao Supabase — onde as 4 tabelas destes routers vivem.

    `search_path=leadgen` espelha o pool da app (`db_leadgen.get_lg_pool`).
    """
    dsn = os.environ["LEADGEN_DB_URL"]
    conn = await asyncpg.connect(dsn, server_settings={"search_path": "leadgen"})
    yield conn
    await conn.close()


@pytest.fixture
async def limpar(lg_conn):
    """Apaga os registros do marcador antes E depois — segunda execução é idêntica."""

    async def _apagar():
        await lg_conn.execute(
            "DELETE FROM rank_intel_overrides WHERE projeto_id = $1 AND keyword = $2",
            PROJETO_MM_INT, KEYWORD_TESTE,
        )
        await lg_conn.execute(
            "DELETE FROM projeto_geo_targets WHERE projeto_id = $1 AND nome = $2",
            PROJETO_MM_INT, GEO_NOME_TESTE,
        )

    await _apagar()
    yield lg_conn
    await _apagar()


def _cliente():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60)


# ---------------------------------------------------------------------------
# ranking.py — ranking_dashboard_cache / ranking_history_cache
# ---------------------------------------------------------------------------

async def test_ranking_devolve_as_mesmas_chaves_de_topo():
    """T1: GET /projetos/{uuid}/ranking → 200 com o payload de sempre."""
    async with _cliente() as c:
        r = await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["status"] == "ok", corpo
    assert set(corpo) == CHAVES_RANKING
    assert corpo["projeto_id"] == PROJETO_MM_UUID
    assert corpo["total"] == len(corpo["keywords"]) > 0


async def test_ranking_history_devolve_series():
    """T2: GET /projetos/{uuid}/ranking/history → 200 com séries por keyword."""
    async with _cliente() as c:
        r = await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking/history")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["status"] == "ok", corpo
    assert set(corpo) == CHAVES_HISTORY
    assert isinstance(corpo["keywords"], list) and corpo["keywords"]
    primeira = corpo["keywords"][0]
    assert set(primeira) == {"keyword", "series"}
    assert set(primeira["series"][0]) == {"date", "serp_position", "sc_position"}


async def test_ranking_report_calcula_sumario():
    """T3: GET /projetos/{uuid}/ranking/report → 200 com sumário e deltas."""
    async with _cliente() as c:
        r = await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking/report")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["status"] == "ok", corpo
    assert corpo["mode"] in ("baseline", "weekly")
    assert corpo["projeto_id"] == PROJETO_MM_INT
    assert set(corpo["summary"]) == {
        "total", "rankeando", "rankeando_delta",
        "gap", "gap_delta", "surpresa", "surpresa_delta",
    }
    for chave in ("top_rankeando", "fell", "rose", "new_surpresa", "critical_gaps"):
        assert isinstance(corpo[chave], list), chave


async def test_ranking_projeto_inexistente_404():
    """T4: GET /ranking com UUID inexistente → 404 pt-BR (resolvido no Postgres)."""
    async with _cliente() as c:
        r = await c.get(f"/projetos/{uuid.uuid4()}/ranking")
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


# ---------------------------------------------------------------------------
# overrides.py — rank_intel_overrides
# ---------------------------------------------------------------------------

async def test_overrides_lista_vazia_ou_nao_devolve_200():
    """T5: GET /projetos/{uuid}/ranking/overrides → 200 com lista."""
    async with _cliente() as c:
        r = await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking/overrides")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


async def test_override_round_trip_completo(limpar):
    """T6: POST → GET mostra → DELETE → GET volta ao estado inicial.

    Round-trip inteiro dentro do Supabase; a resolução do projeto continua no Postgres.
    """
    async with _cliente() as c:
        antes = (await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking/overrides")).json()
        assert KEYWORD_TESTE not in [o["keyword"] for o in antes]

        r = await c.post(
            f"/projetos/{PROJETO_MM_UUID}/ranking/overrides",
            json={"keyword": KEYWORD_TESTE, "action": "promote", "kw_type": "money"},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok"}

        depois = (await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking/overrides")).json()
        criado = [o for o in depois if o["keyword"] == KEYWORD_TESTE]
        assert len(criado) == 1, depois
        assert set(criado[0]) == {"id", "keyword", "action", "kw_type", "created_at"}
        assert criado[0]["action"] == "promote"
        assert criado[0]["kw_type"] == "money"

        # O dado tem que estar mesmo no Supabase, não só na resposta HTTP.
        no_banco = await limpar.fetchval(
            "SELECT action FROM rank_intel_overrides WHERE projeto_id = $1 AND keyword = $2",
            PROJETO_MM_INT, KEYWORD_TESTE,
        )
        assert no_banco == "promote"

        r = await c.delete(f"/projetos/{PROJETO_MM_UUID}/ranking/overrides/{KEYWORD_TESTE}")
        assert r.status_code == 200, r.text

        final = (await c.get(f"/projetos/{PROJETO_MM_UUID}/ranking/overrides")).json()
    assert final == antes


async def test_override_validacao_e_404_preservados(limpar):
    """T7: 400 de validação e 404 de override inexistente continuam iguais."""
    async with _cliente() as c:
        r = await c.post(
            f"/projetos/{PROJETO_MM_UUID}/ranking/overrides",
            json={"keyword": KEYWORD_TESTE, "action": "invalida"},
        )
        assert r.status_code == 400, r.text
        assert "promote" in r.json()["detail"]

        r = await c.post(
            f"/projetos/{PROJETO_MM_UUID}/ranking/overrides",
            json={"keyword": KEYWORD_TESTE, "action": "promote"},
        )
        assert r.status_code == 400, r.text
        assert "kw_type" in r.json()["detail"]

        r = await c.delete(f"/projetos/{PROJETO_MM_UUID}/ranking/overrides/{KEYWORD_TESTE}")
        assert r.status_code == 404, r.text
        assert "Override não encontrado" in r.json()["detail"]


async def test_overrides_projeto_inexistente_404():
    """T8: GET /ranking/overrides com UUID inexistente → 404.

    Prova que a resolução do projeto acontece no Postgres ANTES do Supabase — sem
    FK cross-DB é o único controle que impede travessia entre projetos (T-35-05).
    """
    async with _cliente() as c:
        r = await c.get(f"/projetos/{uuid.uuid4()}/ranking/overrides")
    assert r.status_code == 404, r.text
    assert "Projeto não encontrado" in r.json()["detail"]


# ---------------------------------------------------------------------------
# geo_targets.py — projeto_geo_targets
# ---------------------------------------------------------------------------

async def test_geo_targets_lista_devolve_200():
    """T9: GET /projetos/{uuid}/geo-targets → 200 com lista."""
    async with _cliente() as c:
        r = await c.get(f"/projetos/{PROJETO_MM_UUID}/geo-targets")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


async def test_geo_target_round_trip_completo(limpar):
    """T10: POST → aparece no GET → DELETE desativa → some do GET."""
    async with _cliente() as c:
        antes = (await c.get(f"/projetos/{PROJETO_MM_UUID}/geo-targets")).json()

        r = await c.post(
            f"/projetos/{PROJETO_MM_UUID}/geo-targets",
            json={"nome": GEO_NOME_TESTE, "tipo": "bairro", "volume_estimado": 123},
        )
        assert r.status_code == 200, r.text
        criado = r.json()
        assert set(criado) == {"id", "nome", "tipo", "volume_estimado", "ativo", "created_at"}
        assert criado["nome"] == GEO_NOME_TESTE
        assert criado["tipo"] == "bairro"
        assert criado["volume_estimado"] == 123
        assert criado["ativo"] is True

        depois = (await c.get(f"/projetos/{PROJETO_MM_UUID}/geo-targets")).json()
        assert GEO_NOME_TESTE in [g["nome"] for g in depois]

        # Confere no Supabase, não só na resposta HTTP.
        ativo_no_banco = await limpar.fetchval(
            "SELECT ativo FROM projeto_geo_targets WHERE id = $1", criado["id"],
        )
        assert ativo_no_banco is True

        r = await c.delete(f"/projetos/{PROJETO_MM_UUID}/geo-targets/{criado['id']}")
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok"}

        final = (await c.get(f"/projetos/{PROJETO_MM_UUID}/geo-targets")).json()
        assert final == antes

    # DELETE é soft: o registro continua lá, desativado.
    assert await limpar.fetchval(
        "SELECT ativo FROM projeto_geo_targets WHERE id = $1", criado["id"],
    ) is False


async def test_geo_target_validacao_e_404_preservados():
    """T11: 400 de tipo inválido e 404 de região inexistente continuam iguais."""
    async with _cliente() as c:
        r = await c.post(
            f"/projetos/{PROJETO_MM_UUID}/geo-targets",
            json={"nome": GEO_NOME_TESTE, "tipo": "planeta"},
        )
        assert r.status_code == 400, r.text
        assert "bairro" in r.json()["detail"]

        r = await c.delete(f"/projetos/{PROJETO_MM_UUID}/geo-targets/999999999")
        assert r.status_code == 404, r.text
        assert "Região alvo não encontrada" in r.json()["detail"]


async def test_geo_targets_projeto_id_malformado_422():
    """T12: path param que não é UUID → 422, sem tocar no Supabase."""
    async with _cliente() as c:
        r = await c.get("/projetos/nao-e-uuid/geo-targets")
    assert r.status_code == 422, r.text
