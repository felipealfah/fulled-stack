# Full_AIOS_STACK — Estado do Pipeline LeadGen

Stack de estado e revisão do pipeline LeadGen da FullED: PostgreSQL + FastAPI + dashboard React. É aqui que o Board revisa e aprova cada gate do pipeline (keywords, plano SEO, conteúdo) enquanto os agentes Claude Code produzem os assets no repo `Full_AIOS_LEADGEN`.

## Como rodar

```bash
docker compose up -d          # postgres + migrator + fastapi + frontend
docker compose down           # para tudo
docker compose up --build -d  # rebuild após mudanças de código
docker compose logs -f <svc>  # logs de um serviço
```

Requer `.env` (ver `.env.example`).

| Serviço | Porta | Função |
|---------|-------|--------|
| `postgres` | 5432 | PostgreSQL 17 — banco `fulled` (estado do pipeline) |
| `migrator` | — | Aplica `migrations/*.sql` na subida |
| `fastapi` | 8000 | API REST (review, projetos, ranking, seo_plan, content...) |
| `frontend` | 3001 | Dashboard React (gates de aprovação) |

## Estrutura

```
Full_AIOS_STACK/
├── docker-compose.yml
├── api/                  # FastAPI + asyncpg
│   ├── main.py           # app, CORS, lifespan (pool)
│   ├── db.py             # pool asyncpg
│   ├── schema.sql        # schema base
│   └── routers/          # review, projects, projetos, agent_executions,
│                         # ranking, overrides, seo_plan, geo_targets, content,
│                         # prospeccao (leads outbound do Full_AIOS_PROSPECTOR)
├── frontend/             # React + Vite + Tailwind + TanStack Query
│   └── src/pages/        # KwPlannerGate1/2, SeoPlan, ContentReview,
│                         # ProjetoPipeline, ProjetoRanking, Sites...
└── migrations/           # SQL numerado (001..NNN) — nunca editar aplicadas
```

## Relação com os outros repos

- **`Full_AIOS_LEADGEN`** — agentes e scripts que alimentam/consomem o estado daqui
- **`Full_AIOS_Data`** — dados analíticos (BigQuery); este repo guarda só o estado operacional
- Docs para agentes: [`CLAUDE.md`](CLAUDE.md)
