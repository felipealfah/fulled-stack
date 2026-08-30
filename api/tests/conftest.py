"""Configuração compartilhada dos testes da API.

Roda ANTES de qualquer import da app. Resolve as DUAS connection strings que a
suíte precisa desde a Fase 35 (ADR
Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md):

  DATABASE_URL     → Postgres da Stack (camada de decisão: projetos, pesquisas,
                     agent_executions, leads_prospeccao). Banco de PRODUÇÃO via
                     túnel SSH — abrir antes com `bash Full_AIOS_STACK/vps_tunnel.sh -d`,
                     que publica a VPS em localhost:5433.
  LEADGEN_DB_URL   → Supabase `fahafwvaskiftjbniftw`, schema `leadgen` (camada
                     pré-decisão: content_pages e, nas ondas seguintes, as outras 14).

⚠️ Porta: versões anteriores deste arquivo apontavam para `localhost:5434`, porta do
stack legado `fulled-data`, já desativado. O túnel vivo (`vps_tunnel.sh`, LOCAL_PORT=5433)
responde em **5433**.

T-35-03 — a senha do Postgres de produção NÃO é mais versionada aqui. Ordem de resolução:
  1. `TEST_DATABASE_URL` / `TEST_LEADGEN_DB_URL` no ambiente (override explícito);
  2. os arquivos `.env-prod` / `.env` do repo (ambos gitignored);
  3. DSN sem credencial — a conexão falha com erro claro, em vez de o repo carregar
     um segredo em texto claro.

Rodar a suíte:
    cd Full_AIOS_STACK
    bash vps_tunnel.sh -d
    .venv/bin/python -m pytest api/tests -q
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from dotenv import dotenv_values

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

_STACK_ROOT = _API_DIR.parent
_TUNEL_PORT = "5433"


def _valores_env(nome: str) -> dict:
    """Lê um arquivo .env do repo sem alterar os.environ. {} se não existir."""
    caminho = _STACK_ROOT / nome
    return dotenv_values(caminho) if caminho.exists() else {}


_env_prod = _valores_env(".env-prod")
_env_local = _valores_env(".env")

# --- Postgres da Stack (decisão) --------------------------------------------
_senha_prod = _env_prod.get("POSTGRES_PASSWORD") or ""
_dsn_derivada = (
    f"postgres://fulled:{quote(_senha_prod, safe='')}@127.0.0.1:{_TUNEL_PORT}/fulled"
    if _senha_prod
    else ""
)
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL")
    or _dsn_derivada
    or f"postgres://fulled@127.0.0.1:{_TUNEL_PORT}/fulled",
)

# --- Supabase (pré-decisão, Fase 35) ----------------------------------------
os.environ.setdefault(
    "LEADGEN_DB_URL",
    os.environ.get("TEST_LEADGEN_DB_URL") or _env_local.get("LEADGEN_DB_URL") or "",
)

os.environ.setdefault("AUTH_ENABLED", "false")


@pytest.fixture(autouse=True)
async def _reset_lg_pool_por_teste():
    """Zera `db_leadgen._lg_pool` antes e depois de cada teste.

    Espelha o `_reset_pool_por_teste` que os arquivos de teste já aplicam a
    `db._pool`. Fica no conftest — e não duplicado em 12 arquivos — para que os
    testes que não tocam tabelas migradas continuem funcionando sem edição, e
    para que nenhum pool sobreviva ao event loop do teste anterior.
    """
    import db_leadgen as lg_module

    async def _fechar():
        if lg_module._lg_pool is not None:
            try:
                await lg_module._lg_pool.close()
            except Exception:
                pass
            lg_module._lg_pool = None

    await _fechar()
    yield
    await _fechar()
