-- Migration 027 — REQ-8-05 + REQ-8-08
-- Prepara a base para endpoints REST idempotentes (Phase 10):
--   1) Deleta pesquisa órfã 'Teste Desentupidora DF' (projeto_id_uuid=NULL) — decisão do Board.
--      1a) Antes: deleta FK dependents (agent_executions) — kw_staging cascateia automaticamente
--          (ON DELETE CASCADE); demais tabelas (kw_classification_overrides, kw_scorecard,
--           projeto_seo_plan_pages, scorecard_overrides) não tinham rows para essa pesquisa.
--   2) Cria UNIQUE INDEX natural em pesquisas (nicho, cidade, projeto_id_uuid, papel)
--      — habilita POST /pesquisas/ retornar 409 idempotente (CRIT-5 PITFALLS).
--   3) Cria UNIQUE INDEX em competitor_audits (projeto_id_uuid)
--      — habilita PUT /projetos/{uuid}/competitor-audit com ON CONFLICT (projeto_id_uuid).
--
-- Semântica NULL: default do Postgres (NULLs distintos em UNIQUE).
-- Após o DELETE não sobra nenhuma linha com projeto_id_uuid=NULL, então NULLS NOT DISTINCT é desnecessário.
--
-- REVERSIBILIDADE (rollback manual, executar em janela de manutenção):
--   DROP INDEX IF EXISTS competitor_audits_projeto_uuid_key;
--   DROP INDEX IF EXISTS pesquisas_natural_key;
--   -- O DELETE da órfã não é reversível — recriar manualmente se necessário
--   -- (INSERT INTO pesquisas (projeto_nome, nicho, cidade, status, papel) VALUES (...))

BEGIN;

-- 1a) Cleanup de FK dependents da pesquisa órfã (agent_executions não tem CASCADE).
--     Fazemos DELETE por (projeto_nome, projeto_id_uuid IS NULL) para manter o filtro
--     idempotente e estrito — não afeta outras pesquisas.
DELETE FROM agent_executions
 WHERE pesquisa_id IN (
   SELECT id FROM pesquisas
    WHERE projeto_nome = 'Teste Desentupidora DF'
      AND projeto_id_uuid IS NULL
 );

-- 1b) Cleanup da pesquisa órfã (decisão locada do Board)
--     kw_staging cascateia via ON DELETE CASCADE.
DELETE FROM pesquisas
 WHERE projeto_nome = 'Teste Desentupidora DF'
   AND projeto_id_uuid IS NULL;

-- 2) UNIQUE natural em pesquisas
CREATE UNIQUE INDEX IF NOT EXISTS pesquisas_natural_key
    ON pesquisas (nicho, cidade, projeto_id_uuid, papel);

-- 3) UNIQUE em competitor_audits por UUID (habilita PUT idempotente por UUID no plan 02)
CREATE UNIQUE INDEX IF NOT EXISTS competitor_audits_projeto_uuid_key
    ON competitor_audits (projeto_id_uuid);

COMMIT;
