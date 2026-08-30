-- Migration 034 — competitor_audits.backlink_benchmark (coluna ausente desde sempre)
--
-- PROBLEMA MEDIDO (Fase 35 / Plan 04, 2026-08-30)
-- `api/routers/competitor_audit.py` (PUT) e `api/routers/projetos.py` (GET) referenciam
-- `competitor_audits.backlink_benchmark` no INSERT/SELECT desde a Phase 10. A coluna NUNCA
-- foi criada: `019b_create_competitor_audits.sql` não a declara e nenhuma migration posterior
-- a adiciona. Efeito em produção, verificado ao vivo contra o Postgres da VPS:
--
--   GET /projetos/{uuid}/competitor-audit  -> 500  UndefinedColumnError
--   PUT /projetos/{uuid}/competitor-audit  -> 500  UndefinedColumnError
--
-- Ou seja: a página CompetitorAudit.tsx (que renderiza `gaps.backlink_benchmark`) e a skill
-- `/competitor-audit` estão quebradas. A RESEARCH_SCHEMA.md da Phase 10 documentou a coluna
-- como existente — era um banco anterior, recriado desde então só a partir das migrations.
--
-- POR QUE ADICIONAR EM VEZ DE REMOVER DO CÓDIGO
-- Todo o caminho de escrita (worker/scripts/competitor_audit.py calcula `max(bl_counts)`,
-- worker/scripts/backlink_intel.py atualiza `market_gaps.backlink_benchmark`) e todo o
-- caminho de leitura (frontend/src/lib/api.ts, CompetitorAudit.tsx) já existem. Só a DDL
-- faltava. Remover a coluna do código descartaria dado que os agentes já produzem e mudaria
-- o contrato REQ-8-05 — o oposto do SC-01 da Fase 35.
--
-- POR QUE TAMBÉM NA ORIGEM, E NÃO SÓ NO SUPABASE
-- `scripts/verificar_paridade.sh` monta a lista de colunas por `ordinal_position` no DESTINO
-- e aplica aos DOIS lados. Criar a coluna só no Supabase quebraria o portão de paridade da
-- fase inteira (SC-04). Enquanto a origem existir (até a migration de drop do Plan 11), os
-- dois lados precisam ter a mesma forma.
--
-- INTEGER e não FLOAT: é o tipo declarado em `MarketGaps.backlink_benchmark: int | None`
-- (decisão registrada em 10-02-SUMMARY.md) e o que a RESEARCH_SCHEMA.md documentava.
--
-- REVERSIBILIDADE: ALTER TABLE competitor_audits DROP COLUMN backlink_benchmark;
-- Idempotente: IF NOT EXISTS.

BEGIN;

ALTER TABLE competitor_audits
  ADD COLUMN IF NOT EXISTS backlink_benchmark INTEGER;

COMMENT ON COLUMN competitor_audits.backlink_benchmark IS
  'Benchmark de backlinks dofollow dos concorrentes (maior valor observado). Alimentado por '
  'PUT /projetos/{uuid}/competitor-audit e exibido em CompetitorAudit.tsx. Coluna criada na '
  'migration 034 — o código a referenciava desde a Phase 10 sem ela existir no banco.';

COMMIT;
