-- Migration 009 — agent_executions: coluna projeto_id para execucoes disparadas por projeto
-- Aplicar local: psql -h localhost -U fulled -d fulled -f migrations/009_add_projeto_id_agent_executions.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
--
-- Contexto: rank_intel e disparado por mudanca de status do projeto (nao de pesquisa).
-- A coluna pesquisa_id continua sendo usada por kw_validator (pesquisa-driven).
-- rank_intel usa projeto_id para identificar o contexto de execucao.

ALTER TABLE agent_executions
  ADD COLUMN IF NOT EXISTS projeto_id INT REFERENCES projetos(id) ON DELETE SET NULL;

-- Indice para consultas por projeto (polling rank_intel filtra por agent_name ja coberto
-- pelo idx_agent_executions_pending existente; este indice e util para dashboards/debug)
CREATE INDEX IF NOT EXISTS idx_agent_executions_projeto_id
  ON agent_executions (projeto_id)
  WHERE projeto_id IS NOT NULL;
