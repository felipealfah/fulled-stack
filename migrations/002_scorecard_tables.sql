-- Migration 002 — kw_scorecard + scorecard_overrides
-- Tabelas para Gate 2: scorecard do Agent 6 e overrides do Board
-- Aplicar no VPS: ver instruções abaixo
--
-- Via SSH:
--   scp Full_AIOS_Worker/api/migrations/002_scorecard_tables.sql ubuntu@137.131.139.110:/tmp/
--   ssh ubuntu@137.131.139.110 \
--     "docker cp /tmp/002_scorecard_tables.sql fulled-postgres:/tmp/ && \
--      docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/002_scorecard_tables.sql"

-- 1. Scorecard do Agent 6 (Gate 2 — criado na Phase 4, schema pronto no Marco 1)
CREATE TABLE IF NOT EXISTS kw_scorecard (
  id               SERIAL PRIMARY KEY,
  pesquisa_id      UUID NOT NULL REFERENCES pesquisas(id),
  analysis_version INT NOT NULL DEFAULT 1,
  scorecard_json   JSONB NOT NULL,
  decisao_final    VARCHAR NOT NULL CHECK (decisao_final IN ('GO', 'GO_CONDICIONAL', 'NO-GO')),
  confidence       NUMERIC(3,2),
  status           VARCHAR NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','in_progress','completed','failed','stale')),
  created_at       TIMESTAMP DEFAULT NOW(),
  updated_at       TIMESTAMP DEFAULT NOW()
);

-- 2. Overrides do Board no Gate 2 (treinamento para feedback loop futuro)
CREATE TABLE IF NOT EXISTS scorecard_overrides (
  id               SERIAL PRIMARY KEY,
  pesquisa_id      UUID NOT NULL REFERENCES pesquisas(id),
  analysis_version INT NOT NULL DEFAULT 1,
  decisao_agente   VARCHAR NOT NULL,
  decisao_humana   VARCHAR NOT NULL,
  motivo           TEXT NOT NULL,
  created_at       TIMESTAMP DEFAULT NOW()
);

-- 3. Índices para queries por pesquisa
CREATE INDEX IF NOT EXISTS idx_kw_scorecard_pesquisa
  ON kw_scorecard (pesquisa_id, analysis_version);

CREATE INDEX IF NOT EXISTS idx_scorecard_overrides_pesquisa
  ON scorecard_overrides (pesquisa_id, analysis_version);
