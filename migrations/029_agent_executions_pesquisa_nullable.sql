-- Migration 029 — Plan 12-02 (Milestone 8 cleanup)
--
-- Torna `agent_executions.pesquisa_id` nullable para permitir que skills
-- content/site registrem execuções vinculadas apenas ao projeto (via
-- `projeto_id_uuid`) — sem exigir uma `pesquisa` aprovada.
--
-- Motivação: o novo endpoint POST /projetos/{id}/agent-executions (Plan 12-02)
-- suporta site-builder rodando ANTES do gate único (projeto novo, sem
-- pesquisa aprovada). Também aceita `pesquisa_id` opcional para retro-compat
-- com content-writer/content-reviewer (que preferencialmente vinculam à
-- pesquisa quando existe).
--
-- Também garante que os handlers existentes (POST /agent-executions/ e
-- PATCH /projetos/{id} publish) possam popular `projeto_id_uuid` corretamente
-- via lookup — a coluna já existe (migration 020), só faltava o handler usar.
--
-- REVERSIBILIDADE (rollback manual, só se todas as rows órfãs foram limpas):
--   UPDATE agent_executions SET pesquisa_id = '00000000-0000-0000-0000-000000000000'::uuid
--     WHERE pesquisa_id IS NULL;
--   ALTER TABLE agent_executions ALTER COLUMN pesquisa_id SET NOT NULL;
--
-- Idempotente: ALTER … DROP NOT NULL não falha se já estiver nullable.

BEGIN;

ALTER TABLE agent_executions
  ALTER COLUMN pesquisa_id DROP NOT NULL;

COMMIT;
