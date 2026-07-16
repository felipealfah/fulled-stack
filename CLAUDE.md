# CLAUDE.md — Full_AIOS_STACK

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Arquitetura

`Full_AIOS_STACK` guarda o **estado do pipeline LeadGen** (Postgres) e as interfaces de revisão humana (FastAPI + dashboard React). Os assets do pipeline (keywords, planos SEO, conteúdo, sites) vivem no repo `Full_AIOS_LEADGEN` — aqui fica só o estado e os gates de aprovação.

- `api/` — FastAPI + asyncpg. `main.py` (app/lifespan), `db.py` (pool), `routers/`: `review`, `projects`, `projetos`, `agent_executions`, `ranking`, `overrides`, `seo_plan`, `geo_targets`, `content`, `prospeccao` (leads outbound do `Full_AIOS_PROSPECTOR`)
- `frontend/` — React + Vite + Tailwind + TanStack Query. Páginas em `src/pages/` (gates e revisões), client HTTP tipado em `src/lib/`
- `migrations/` — SQL numerado sequencial (`001_...` a `NNN_...`), aplicado pelo serviço `migrator` na subida. **Nunca editar migration já aplicada — criar nova.**
- `docker-compose.yml` — postgres:17 (5432, db `fulled`), migrator, fastapi (8000), frontend (3001)

## Commands

```bash
docker compose up -d              # sobe a stack
docker compose up --build -d      # rebuild após mudança de código
docker compose logs -f fastapi    # logs da API
```

Requer `.env` (ver `.env.example`).

## Conventions

### Python (api/)
- Erros: `raise HTTPException(status_code, "mensagem em pt-BR")`; checar 404 antes de mutações
- `async with pool.acquire() as conn:` por handler; `fetchrow`/`fetch`/`fetchval`/`execute`
- Queries parametrizadas `$1, $2, ...` — nunca interpolar valores via f-string (exceção: nomes de coluna em `SET` dinâmico)
- Converter `asyncpg.Record` com `dict(row)` antes de retornar
- Pydantic models `{Resource}{Action}`: `KeywordUpdate`, `AgentExecutionCreate`; partial update via `model_dump(exclude_none=True)`
- Types com `|` (`str | None`), sem `typing.Optional` em código novo
- Domínio em português: `pesquisa`, `nicho`, `projeto_nome`

### TypeScript (frontend/)
- Componentes `PascalCase.tsx`, utils `camelCase.ts`, handlers prefixo `handle`
- Server state via TanStack Query v5 (`useQuery` + `invalidateQueries` após mutações); sem store global
- Axios com `baseURL` de `VITE_API_URL` (fallback `/api`); generics `api.get<T>()`
- Tailwind inline, dark theme (`bg-gray-950`), cores semânticas: `emerald` = GO/aprovado, `red` = NO-GO, `amber` = alerta; `font-mono`
- Textos de UI em pt-BR

### Status flows
- `pesquisas.status`: `pending_review` → `approved` | `rejected`
- `kw_staging.status`: `pending` → `approved` | `rejected`
- `agent_executions.status`: `pending` → `in_progress` → `completed` | `failed`

### Outros
- CPC em BRL, armazenado como micros na API e convertido para decimal
- GO/NO-GO: mínimo 3 keywords com volume >=200, >=30% low competition, >=500 volume mensal total
