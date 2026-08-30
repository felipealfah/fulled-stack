"""db_leadgen.py — pool asyncpg do Supabase (dados pré-decisão do LeadGen).

Fase 35 / D-01 / D-02. ADR:
Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

Clone deliberado de `db.py` — mesmo formato de singleton lazy e o **mesmo** codec JSONB.
O codec não é opcional: `content_pages.review_report` (e, nas ondas seguintes,
`competitor_audits`, `backlink_intel`, `projeto_seo_plan_pages_intel`) é JSONB, e sem o
codec o asyncpg devolve string — o spread no frontend corrompe o dado (bug histórico do
Plan 08-BUG).

Connection string (`LEADGEN_DB_URL`, no `.env` — nunca no código, C-06):
  - **Porta 5432** = sessão persistente (conexão direta ou Supavisor *session* pooler).
    Prepared statements funcionam normalmente, que é o que o asyncpg assume por padrão.
  - A porta **6543** (Supavisor *transaction* mode) NÃO pode ser usada como está: o backend
    volta ao pool entre transações e o nome do prepared statement colide entre clientes
    (`DuplicatePreparedStatementError`). Se algum dia for necessária, exige
    `statement_cache_size=0` no `create_pool` ou `?pgbouncer=true` na URL.
  - `sslmode=require` é obrigatório — o tráfego atravessa a internet pública.

`search_path=leadgen` é o que permite todo o SQL existente continuar dizendo
`FROM content_pages` sem prefixo de schema. `pg_catalog` continua implícito, então
`gen_random_uuid()`, `now()` e `jsonb_set` seguem resolvendo.

Pool menor que o do Postgres da Stack (`min_size=1, max_size=5`): mantém uma conexão
quente — evitando o custo de handshake TLS por request (Pitfall 8) — sem inflar o pooler
gerenciado do Supabase.
"""

import asyncpg
import json
import os

_lg_pool: asyncpg.Pool | None = None


async def _init_conn(conn):
    await conn.set_type_codec(
        'jsonb',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog',
    )


async def get_lg_pool() -> asyncpg.Pool:
    global _lg_pool
    if _lg_pool is None:
        _lg_pool = await asyncpg.create_pool(
            os.environ["LEADGEN_DB_URL"],
            min_size=1,
            max_size=5,
            init=_init_conn,
            server_settings={"search_path": "leadgen"},
        )
    return _lg_pool


async def close_lg_pool():
    global _lg_pool
    if _lg_pool:
        await _lg_pool.close()
        _lg_pool = None
