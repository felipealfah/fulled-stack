# SPEC — Endpoints de Gestão de Keywords & Sincronização de Arquitetura

**Autor:** revisão de arquitetura (sessão 2026-07-26)
**Destino:** agente desenvolvedor — repos `Full_AIOS_STACK` (FastAPI + Postgres) e frontend React (`localhost:3001` / dashboard)
**Objetivo:** fechar gaps de escrita no pipeline LeadGen que hoje forçam workarounds client-side ou impedem sincronizar edições manuais do vault com o Postgres de produção.

---

## Contexto e motivação

Durante a montagem do projeto `maridodealuguel` (UUID `cd185753-fbdc-4ae1-81c3-6568250cdfcb`) foram feitas edições manuais no vault (`inteligence/projetos/{slug}/seo/seo_plan.json` + briefs): redução de um silo, adição de ~46 geo pages sem volume, correções de arquitetura. Ao tentar refletir isso no Postgres, ficou claro que **a API só tem rotas de escrita de keyword na criação** (`POST /pesquisas/`) e de scores (`PATCH .../keywords/bulk-intel`). Não há como:

1. Reclassificar `kw_type` de keywords já persistidas (ex.: colapsar um silo → seções).
2. Sincronizar a arquitetura de páginas do vault (URLs/titles/kw_type) para o Postgres sem rodar o `/content-writer`.
3. Apagar uma pesquisa para re-rodar limpo.
4. Popular o intel (`competitive_score`) nas `seo_plan_pages` — TODO documentado da Phase 12.
5. Listar keywords de um projeto por filtro sem iterar pesquisas client-side.

Esta spec cobre esses cinco pontos. **O #1 é o pedido imediato; #2–#5 são recomendações priorizadas** (ver tabela no fim).

---

## Convenções (valem para todos os endpoints)

- **Auth:** header `x-api-key: $STACK_API_KEY` (middleware `auth.py`). 401 sem/errada.
- **Base URL:** `https://api.fulled.com.br` (`FASTAPI_URL`).
- **projeto_id:** UUID canônico. Aceitar inteiro legado só onde já existe (`id_int_legado`). BQ continua INT64 (fora do escopo).
- **Erros:** manter o envelope atual (mensagem PT em `detail`/`body_pt`) — o `ApiClient` client-side só levanta em 4xx e faz retry 3x em 5xx.
- **Idempotência:** todas as rotas de bulk abaixo devem ser idempotentes (rodar 2x = mesmo estado final).
- **Tabelas citadas** (`kw_staging`, `pesquisas`, `seo_plan_pages`, `content_pages`): **confirmar nomes/colunas reais no repo da Stack** — os nomes aqui seguem o CLAUDE.md do LeadGen.

---

## 1. [OBRIGATÓRIO] Reclassificar `kw_type` em bulk

Permite alterar a classificação de keywords já persistidas. Caso de uso imediato: colapsar o silo de desentupimento (marcar sub-hubs/geo como `SECAO`, mantendo só o hub). Já existe o script client-side `worker/scripts/reclassify_desentupimento.py` que produz exatamente o payload abaixo — só falta a rota.

### API

```
PATCH /pesquisas/{pesquisa_id}/keywords/bulk-reclassify
```

**Request body:**
```json
{
  "items": [
    { "keyword_id": 12345, "kw_type": "SECAO" },
    { "keyword_id": 12346, "kw_type": "DESCARTA" }
  ]
}
```

**Regras de validação:**
- `kw_type` ∈ `{PAGINA_PRINCIPAL, PAGINA_GEO, LOCALIDADE, SECAO, SURPRESA, DESCARTA}` (rejeitar 422 fora do enum — reaproveitar o mesmo enum de `POST /pesquisas/`).
- `keyword_id` deve pertencer à `pesquisa_id` do path (senão vai para `not_found`, não atualiza).
- `items` de 1 a 2000; acima disso 422 (client faz chunk).

**Comportamento (SQL):**
```sql
UPDATE kw_staging
   SET kw_type = :kw_type, updated_at = now()
 WHERE id = :keyword_id AND pesquisa_id = :pesquisa_id;
```
Rodar em transação única; ids inexistentes ou de outra pesquisa entram em `not_found` sem abortar o resto.

**Response 200:**
```json
{ "updated": 158, "not_found": [], "invalid": [] }
```

**Erros:** 401 (auth), 404 (pesquisa não existe), 422 (enum/tamanho inválido).

### Frontend

Na tela de keywords da pesquisa (dashboard, view por `pesquisa_id`):
- Coluna `kw_type` vira **editável inline** (dropdown com o enum).
- Ação em lote: seleção múltipla de linhas → "Reclassificar como…" → dispara o PATCH bulk com as linhas selecionadas.
- Feedback: toast `updated=N`; destacar linhas `not_found` se houver.
- **Guard de segurança:** confirmar antes de reclassificar em massa se o projeto estiver `publicado` (pode afetar o próximo seo-architect/rank tracking).

### Testes sugeridos
- bulk com 3 ids válidos → `updated=3`.
- id de outra pesquisa → cai em `not_found`, os demais atualizam.
- kw_type fora do enum → 422, nenhum aplicado.
- idempotência: rodar 2x → segundo `updated` reflete só o que ainda mudava (ou re-aplica sem efeito colateral).

---

## 2. [ALTA] Sincronizar arquitetura de páginas a partir do vault

**Motivação — o gap mais estratégico.** Hoje a arquitetura de páginas (URLs, titles, kw_type, hierarquia) só entra no Postgres quando o `/content-writer` roda e escreve `content_pages` **com conteúdo**. Não há como refletir uma edição estrutural (remover/adicionar página, trocar title) sem gerar conteúdo. Isso desacopla mal "arquitetura definida" de "conteúdo escrito" e faz o dashboard ficar defasado do vault. Este endpoint faz o upsert **estrutural** (sem corpo de conteúdo) da lista de páginas do `seo_plan.json`.

### API

```
PUT /projetos/{projeto_id}/seo-plan/pages/sync
```

**Request body** (derivado direto do `seo_plan.json` do vault — o script client-side monta):
```json
{
  "arquitetura": "v1",
  "replace": true,
  "pages": [
    {
      "url": "/desentupimento/",
      "tipo": "servico",
      "kw_type": "PAGINA_PRINCIPAL",
      "titulo": "Desentupidora em Brasília DF · 24h...",
      "meta_description": "…",
      "h1": "…",
      "keyword_primaria": "desentupidora brasília",
      "pesquisa_id": "6b139e55-…",
      "papel_pesquisa": "servico",
      "servico_pai": "/desentupimento/",
      "sem_volume": false
    }
  ]
}
```

**Comportamento:**
- Upsert por chave natural `(projeto_id, url)`.
- Se `replace: true`: páginas do projeto **ausentes** no payload são marcadas `deleted`/`arquivada` (soft-delete, não DROP) — cobre remoções feitas no vault.
- Preservar colunas de conteúdo já existentes em `content_pages` (não sobrescrever o corpo com null) — este endpoint mexe só nos campos estruturais.
- Popular `projeto_id_uuid` para o dashboard scoped enxergar.

**Tabela alvo:** recomendo `content_pages` (estrutural), **confirmar** se já existe coluna p/ status estrutural vs conteúdo; se o schema separar `seo_plan_pages` × `content_pages`, aplicar nas colunas estruturais da que o dashboard lê.

**Response 200:**
```json
{ "created": 46, "updated": 30, "archived": 9 }
```

### Frontend
- View "Páginas" por projeto: tabela com URL, tipo, kw_type, title, status (nova/atualizada/arquivada), flag `sem_volume`.
- Badge "defasado do vault" quando `updated_at` do vault > `synced_at` (se der para comparar).
- Read-only nesta fase (a edição continua no vault); botão "Sincronizar do vault" só dispara o PUT com o payload que o script gerou.

### Nota
Isso **não substitui** o `/content-writer` — apenas registra a arquitetura antes do conteúdo. Deixa o dashboard fiel ao vault mesmo entre seo-architect e content-writer.

---

## 3. [MÉDIA] Apagar pesquisa (cascade)

**Motivação:** hoje `POST /pesquisas/` é idempotente por `(nicho, cidade, projeto_id_uuid, papel)` → 409 se já existe, e **não há DELETE**. Sem isso, não dá para re-rodar `/kw-validator` limpo (ex.: reclassificação grande, correção de escopo). O `ApiClient` já tem método `delete()` — falta a rota no servidor.

### API
```
DELETE /pesquisas/{pesquisa_id}?force=false
```
**Comportamento:**
- Cascade: remove linhas de `kw_staging` da pesquisa e referências em `seo_plan_pages` ligadas a ela.
- **Guard:** recusar (409) se o projeto estiver `publicado`, a menos que `force=true`.
- Idealmente soft-delete (`deleted_at`) para auditoria; hard-delete só com `force=true`.

**Response:** `204 No Content` (ou `{ "deleted_keywords": N }`).
**Erros:** 404, 409 (projeto publicado sem force).

### Frontend
- Botão "Excluir pesquisa" na lista de pesquisas do projeto, com modal de confirmação (mostrar quantas keywords serão removidas) e checkbox "forçar" desabilitado por padrão.

---

## 4. [MÉDIA] Popular intel nas seo_plan_pages (TODO Phase 12)

**Motivação:** gap **já documentado** no `.claude/commands/seo-architect.md` (passo 4): _"endpoint POST /projetos/{id}/seo-plan/populate-intel não existe … scores intel ficarão pendentes até criar endpoint"_. Sem ele, `competitive_score`/`difficulty_label`/`top_competitor` não descem do `kw_staging` para as `seo_plan_pages`, e o seo-architect trabalha com intel incompleto.

### API
```
POST /projetos/{projeto_id}/seo-plan/populate-intel
```
**Comportamento:** para cada `seo_plan_page` do projeto, buscar as keywords correspondentes no `kw_staging` (via `pesquisa_id`/`papel`) e copiar `competitive_score`, `difficulty_label`, `top_competitor_url` (agregado por região quando aplicável). Idempotente.
**Response:** `{ "pages_updated": N, "pages_sem_intel": [ids] }`.
**Frontend:** nenhum (rota de sync backend; pode ser exposta como botão "Recalcular intel" na tela do SEO plan).

---

## 5. [MÉDIA] Listar keywords do projeto com filtros

**Motivação:** hoje `GET /projetos/{id}/keywords?status=approved` **não existe** — `run_serp_browser.py`, `run_serp_silver.py` e o rank-intel iteram `projeto.pesquisas` + `GET /pesquisas/{ppid}` e filtram client-side (workaround explícito no código). Uma rota única elimina N requests e centraliza a regra.

### API
```
GET /projetos/{projeto_id}/keywords?status=approved&kw_type=PAGINA_GEO&pesquisa_id=...
```
- Filtros opcionais e combináveis: `status`, `kw_type` (aceitar `!=DESCARTA` como caso comum), `pesquisa_id`, `papel`.
- Paginação (`limit`/`offset`) e ordenação por `avg_monthly_searches DESC`.

**Response:**
```json
{ "total": 230, "items": [ { "id": 1, "keyword": "...", "kw_type": "PAGINA_GEO", "status": "approved", "avg_monthly_searches": 210, "pesquisa_id": "..." } ] }
```
**Frontend:** alimenta uma tabela de keywords **por projeto** (visão consolidada, hoje inexistente) com os mesmos filtros — e é onde a reclassificação em lote do #1 pode viver também.

---

## 6. [BAIXA / quick wins]

- `GET /projetos/?id_int_legado=<int>` — hoje não existe; scripts fazem `GET /projetos/` + filtro client-side. Trivial e remove workaround.
- Expor `updated_at` em `kw_staging` (se ainda não houver) — necessário para os endpoints de bulk acima refletirem "última alteração" no dashboard.

---

## Priorização recomendada

| # | Endpoint | Valor | Esforço | Depende de |
|---|----------|-------|---------|-----------|
| 1 | `PATCH /pesquisas/{id}/keywords/bulk-reclassify` | Alto (desbloqueia o caso atual) | Baixo | — |
| 2 | `PUT /projetos/{id}/seo-plan/pages/sync` | Alto (vault↔Postgres) | Médio | schema content_pages |
| 4 | `POST /projetos/{id}/seo-plan/populate-intel` | Médio (fecha TODO Phase 12) | Baixo | seo_plan_pages |
| 5 | `GET /projetos/{id}/keywords` (filtros) | Médio (mata workarounds) | Baixo | — |
| 3 | `DELETE /pesquisas/{id}` (cascade) | Médio (re-run limpo) | Baixo | guard publicado |
| 6 | quick wins | Baixo | Trivial | — |

**Sugestão de sprint 1:** #1 + #5 (baixo esforço, alto retorno imediato) e depois #2 (o que realmente resolve o vault↔Postgres). #3 e #4 podem ir junto por serem pequenos.

---

## Checklist de entrega (para o agente dev)

- [ ] Rotas com auth `x-api-key` e validação de enum reaproveitada de `POST /pesquisas/`.
- [ ] Todas as rotas de bulk idempotentes e em transação.
- [ ] Testes (pytest) por rota, incluindo casos `not_found`/`invalid`/guard.
- [ ] Migração Postgres se faltar coluna (`deleted_at`, `synced_at`, `updated_at`) — usar `ADD COLUMN IF NOT EXISTS`.
- [ ] Frontend: dropdown de `kw_type` + ação em lote (#1), view Páginas por projeto (#2), view Keywords por projeto com filtros (#5).
- [ ] Atualizar `CLAUDE.md` (tabela de endpoints por skill) e `PIPELINE.md` após subir para produção.
- [ ] ADR em `inteligence/decisoes/` registrando as novas rotas de escrita de kw_type + sync de arquitetura.
