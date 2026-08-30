"""SC-02 — o cliente do CRM não alcança o schema `leadgen` do Supabase.

ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md
Migrations que este arquivo trava:
  Full_AIOS_LEADGEN/leadgen_crm/supabase/migrations/20260829120000_create_schema_leadgen.sql
  Full_AIOS_LEADGEN/leadgen_crm/supabase/migrations/20260829130100_leadgen_rls_deny_anon.sql

A Fase 35 moveu 15 tabelas da camada pré-decisão para dentro do **mesmo projeto
Supabase** que serve o `leadgen_crm` — cujo `anon_key` é público por definição (vai
no bundle do frontend). O isolamento é feito em três camadas independentes:

  1. o schema `leadgen` **não está exposto** ao PostgREST (só `public` e `graphql_public`);
  2. `REVOKE ALL` + `ALTER DEFAULT PRIVILEGES` para `anon` e `authenticated`;
  3. RLS habilitada nas 15 tabelas, com **zero** policies.

Cada camada sozinha já negaria; as três juntas fazem com que qualquer uma ser
desfeita por engano — uma policy criada no painel, um schema adicionado à lista de
exposição, um `GRANT` num script — ainda não abra o dado. Este arquivo mede as três
contra o Supabase **real**, com a chave anônima e com a chave de serviço, porque o
isolamento tem de vir do schema não exposto e **não** de qual chave foi usada.

O caso de controle em `public` é obrigatório e não decorativo: sem ele, um Supabase
fora do ar faria todas as negações "passarem" por engano. Pelo mesmo motivo toda
negação exige um corpo de erro do **PostgREST** (campo `code` começando por `PGRST`)
— uma falha de rede levanta exceção, nunca vira verde.

Pré-condições:
- `SUPABASE_URL` + chave anônima + chave de serviço do projeto do `leadgen_crm`,
  resolvidas na ordem: variáveis `TEST_SUPABASE_*` → `Full_AIOS_LEADGEN/leadgen_crm/.env`
  → `Full_AIOS_STACK/.env`. Faltando qualquer uma, o módulo é **pulado** com mensagem
  em pt-BR — configuração ausente jamais pode se confundir com falha de segurança.
- `LEADGEN_DB_URL` resolvida pelo conftest.py (só para as checagens de catálogo).

Nenhuma chave é escrita neste arquivo (T-35-03).

Rodar:
    cd Full_AIOS_STACK
    .venv/bin/python -m pytest api/tests/test_rls_leadgen_schema.py -v
"""

import os
import sys
from pathlib import Path

import asyncpg
import httpx
import pytest
from dotenv import dotenv_values

_API_DIR = Path(__file__).resolve().parents[1]
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

_STACK_ROOT = _API_DIR.parent
_RAIZ = _STACK_ROOT.parent

# Tabela do schema `public` usada como controle de vida do Supabase. É a mesma
# sanidade que o Plan 35-01 executou à mão (`/rest/v1/projetos` → 200 com o anon_key):
# a chave é válida e o PostgREST está no ar; o que bloqueia é o schema.
TABELA_CONTROLE_PUBLIC = "projetos"

# As 4 tabelas que o plano nomeia explicitamente. A cobertura das 15 vem do catálogo,
# em `test_todas_as_tabelas_migradas_negam_as_duas_chaves`.
TABELAS_CITADAS = ("kw_staging", "content_pages")


def _fontes_de_credencial() -> list[dict]:
    """Fontes candidatas, da mais explícita para a mais implícita.

    Cada fonte é usada **inteira** (URL e chaves do mesmo lugar): misturar a URL de
    uma origem com a chave de outra poderia apontar para projetos Supabase diferentes
    e produzir uma negação que não prova nada.
    """
    return [
        {
            "nome": "variáveis TEST_SUPABASE_*",
            "url": os.environ.get("TEST_SUPABASE_URL", ""),
            "anon": os.environ.get("TEST_SUPABASE_ANON_KEY", ""),
            "service": os.environ.get("TEST_SUPABASE_SERVICE_ROLE_KEY", ""),
        },
        _de_arquivo(
            "Full_AIOS_LEADGEN/leadgen_crm/.env",
            _RAIZ / "Full_AIOS_LEADGEN" / "leadgen_crm" / ".env",
        ),
        _de_arquivo("Full_AIOS_STACK/.env", _STACK_ROOT / ".env"),
        _de_arquivo("Full_AIOS_STACK/.env-prod", _STACK_ROOT / ".env-prod"),
    ]


def _de_arquivo(nome: str, caminho: Path) -> dict:
    v = dotenv_values(caminho) if caminho.exists() else {}
    return {
        "nome": nome,
        "url": (v.get("SUPABASE_URL") or "").strip(),
        "anon": (v.get("SUPABASE_ANON_KEY") or "").strip(),
        "service": (v.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip(),
    }


def _credenciais() -> dict | None:
    """Primeira fonte que forneça URL + as DUAS chaves. None se nenhuma servir."""
    for fonte in _fontes_de_credencial():
        if fonte["url"] and fonte["anon"] and fonte["service"]:
            return {**fonte, "url": fonte["url"].rstrip("/")}
    return None


_CRED = _credenciais()
if _CRED is None:
    pytest.skip(
        "SC-02 não verificado: faltam SUPABASE_URL, SUPABASE_ANON_KEY ou "
        "SUPABASE_SERVICE_ROLE_KEY. Defina TEST_SUPABASE_URL / TEST_SUPABASE_ANON_KEY / "
        "TEST_SUPABASE_SERVICE_ROLE_KEY no ambiente, ou preencha "
        "Full_AIOS_LEADGEN/leadgen_crm/.env. Configuração ausente NÃO é prova de "
        "isolamento — por isso o módulo é pulado em vez de passar.",
        allow_module_level=True,
    )

_URL = _CRED["url"]
CHAVES = (("anon_key", _CRED["anon"]), ("service_role_key", _CRED["service"]))


def _headers(chave: str, schema: str | None = None) -> dict:
    h = {"apikey": chave, "Authorization": f"Bearer {chave}"}
    if schema:
        # Header do PostgREST para escolher o schema explicitamente. É a tentativa
        # óbvia de quem já sabe que o dado mudou de schema.
        h["Accept-Profile"] = schema
    return h


def _exige_negacao(r: httpx.Response, contexto: str) -> None:
    """Nega = não-200, sem linha nenhuma no corpo, e resposta vinda do PostgREST.

    Deliberadamente NÃO assere um código HTTP específico: o PostgREST varia entre
    404 (`PGRST205`, tabela ausente do cache do schema `public`) e 406 (`PGRST106`,
    schema não exposto) conforme a versão e o header enviado. Travar o número
    transformaria um upgrade do Supabase em falha de segurança falsa.

    A exigência do `code` `PGRST*` é o que impede o falso verde: se o Supabase
    estivesse fora, `httpx` levantaria exceção — e se um proxy respondesse qualquer
    outra coisa, o corpo não teria o código.
    """
    assert r.status_code != 200, f"{contexto}: PostgREST respondeu 200 — {r.text[:300]}"
    corpo = r.json()
    assert isinstance(corpo, dict), (
        f"{contexto}: o corpo é uma lista — isso é payload de SELECT bem-sucedido, "
        f"não uma negação: {r.text[:300]}"
    )
    assert str(corpo.get("code", "")).startswith("PGRST"), (
        f"{contexto}: a resposta não veio do PostgREST (sem código PGRST*): {r.text[:300]}"
    )
    # Nenhuma chave de dado escapando no corpo do erro.
    assert "data" not in corpo, f"{contexto}: corpo de erro com dado: {r.text[:300]}"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(timeout=30) as c:
        yield c


@pytest.fixture
async def lg_conn():
    """Conexão direta ao Supabase — só para as checagens de catálogo."""
    dsn = os.environ.get("LEADGEN_DB_URL") or ""
    if not dsn:
        pytest.skip("LEADGEN_DB_URL não resolvida — checagem de catálogo não executada")
    conn = await asyncpg.connect(dsn)
    yield conn
    await conn.close()


# ── Controle de vida: sem ele, um Supabase fora do ar faria tudo passar ──────


@pytest.mark.asyncio
async def test_controle_o_supabase_esta_no_ar_e_a_chave_anonima_e_valida(http):
    """`public` continua legível com o `anon_key`, conforme as policies do CRM.

    Este é o teste que dá sentido a todos os outros deste arquivo. Se ele falhar,
    as negações abaixo não provam isolamento nenhum — provam indisponibilidade.
    """
    r = await http.get(
        f"{_URL}/rest/v1/{TABELA_CONTROLE_PUBLIC}?select=id&limit=1",
        headers=_headers(_CRED["anon"]),
    )
    assert r.status_code == 200, (
        f"controle falhou: `public.{TABELA_CONTROLE_PUBLIC}` deveria responder 200 com o "
        f"anon_key. Sem este 200 as negações deste arquivo não distinguem "
        f"'negado por isolamento' de 'Supabase fora do ar'. → {r.status_code} {r.text[:300]}"
    )
    assert isinstance(r.json(), list), r.text[:300]


# ── SC-02, camada 1: o schema não está exposto ao PostgREST ─────────────────


@pytest.mark.asyncio
async def test_anon_key_nao_le_kw_staging_nem_content_pages(http):
    """As duas tabelas que o ADR nomeia, com e sem o header de schema explícito."""
    for tabela in TABELAS_CITADAS:
        for perfil in (None, "leadgen"):
            r = await http.get(
                f"{_URL}/rest/v1/{tabela}?select=id&limit=1",
                headers=_headers(_CRED["anon"], perfil),
            )
            _exige_negacao(r, f"anon_key → {tabela} (Accept-Profile={perfil})")


@pytest.mark.asyncio
async def test_service_role_key_tambem_nao_alcanca_o_schema_leadgen(http):
    """O isolamento vem do schema não exposto, **não** de qual chave é usada.

    A chave de serviço ignora RLS por definição. Se ela lesse o schema pela REST API,
    o isolamento seria apenas "a chave certa não vazou" — uma garantia sobre segredo,
    não sobre superfície. A negação aqui é o que torna SC-02 uma propriedade da
    arquitetura.
    """
    for tabela in TABELAS_CITADAS:
        for perfil in (None, "leadgen"):
            r = await http.get(
                f"{_URL}/rest/v1/{tabela}?select=id&limit=1",
                headers=_headers(_CRED["service"], perfil),
            )
            _exige_negacao(r, f"service_role_key → {tabela} (Accept-Profile={perfil})")


@pytest.mark.asyncio
async def test_todas_as_tabelas_migradas_negam_as_duas_chaves(http, lg_conn):
    """As 15 tabelas, não só as duas citadas — e a lista vem do **catálogo**.

    Ler a lista de `pg_tables` em vez de fixá-la aqui faz com que uma 16ª tabela
    migrada no futuro entre na cobertura sozinha. Uma lista escrita à mão só
    protegeria o que alguém lembrou de escrever.
    """
    tabelas = [
        r["tablename"]
        for r in await lg_conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'leadgen' ORDER BY tablename"
        )
    ]
    assert len(tabelas) >= 15, f"esperava as 15 tabelas de D-02, achei {tabelas}"

    for tabela in tabelas:
        for nome_chave, chave in CHAVES:
            for perfil in (None, "leadgen"):
                r = await http.get(
                    f"{_URL}/rest/v1/{tabela}?select=*&limit=1",
                    headers=_headers(chave, perfil),
                )
                _exige_negacao(r, f"{nome_chave} → {tabela} (Accept-Profile={perfil})")


# ── SC-02, camadas 2 e 3: grants revogados e RLS sem policy ─────────────────


@pytest.mark.asyncio
async def test_catalogo_zero_policies_e_rls_habilitada_em_todas(lg_conn):
    """Camada 3 — RLS ligada em todas as tabelas do schema, com zero policies.

    "RLS habilitada" sem policy nenhuma nega tudo para roles não privilegiadas. Uma
    policy criada por engano no painel (o modo mais provável de isto se perder) faz
    a primeira asserção falhar.
    """
    policies = await lg_conn.fetch(
        "SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'leadgen'"
    )
    assert policies == [], (
        f"o schema leadgen ganhou policy(ies): {[(p['tablename'], p['policyname']) for p in policies]} "
        f"— com RLS habilitada, uma policy é justamente o que ABRE o dado"
    )

    sem_rls = await lg_conn.fetch(
        """SELECT c.relname
             FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'leadgen'
              AND c.relkind IN ('r', 'p')
              AND NOT c.relrowsecurity"""
    )
    assert sem_rls == [], f"tabelas do schema leadgen sem RLS: {[r['relname'] for r in sem_rls]}"


@pytest.mark.asyncio
async def test_catalogo_zero_grants_para_anon_e_authenticated(lg_conn):
    """Camada 2 — nenhum privilégio de tabela para as roles do PostgREST.

    Inclui `authenticated`: um usuário logado do CRM é tão externo à camada
    pré-decisão quanto um anônimo.
    """
    grants = await lg_conn.fetch(
        """SELECT grantee, table_name, privilege_type
             FROM information_schema.role_table_grants
            WHERE table_schema = 'leadgen'
              AND grantee IN ('anon', 'authenticated')"""
    )
    assert grants == [], (
        "grants encontrados no schema leadgen: "
        f"{[(g['grantee'], g['table_name'], g['privilege_type']) for g in grants]}"
    )
