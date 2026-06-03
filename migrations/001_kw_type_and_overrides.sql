-- Migration 001 — kw_type + tabelas de override e execução de agentes
-- Aplicar no VPS: psql $DATABASE_URL -f migrations/001_kw_type_and_overrides.sql

-- 1. Adiciona kw_type na tabela de staging
ALTER TABLE kw_staging
  ADD COLUMN IF NOT EXISTS kw_type VARCHAR
    CHECK (kw_type IN ('principal', 'silo', 'geo', 'descarta'));

-- 2. Rastreamento de execução por agente (retomada de falha)
CREATE TABLE IF NOT EXISTS agent_executions (
  id               SERIAL PRIMARY KEY,
  pesquisa_id      UUID NOT NULL REFERENCES pesquisas(id),
  analysis_version INT NOT NULL DEFAULT 1,
  agent_name       VARCHAR NOT NULL,
  status           VARCHAR NOT NULL CHECK (status IN ('pending','in_progress','completed','failed')),
  progress_data    JSONB,
  error_message    TEXT,
  started_at       TIMESTAMP,
  completed_at     TIMESTAMP,
  retry_count      INT DEFAULT 0,
  created_at       TIMESTAMP DEFAULT NOW(),
  updated_at       TIMESTAMP DEFAULT NOW()
);

-- 3. Overrides do Board no Gate 1 (training data para futuro feedback loop)
CREATE TABLE IF NOT EXISTS kw_classification_overrides (
  id                    SERIAL PRIMARY KEY,
  pesquisa_id           UUID NOT NULL REFERENCES pesquisas(id),
  analysis_version      INT NOT NULL DEFAULT 1,
  keyword               VARCHAR NOT NULL,
  classificacao_agente  VARCHAR,          -- nullable até agent 2+3 existir
  classificacao_humana  VARCHAR NOT NULL,
  comentario            TEXT,
  created_at            TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_overrides_pesquisa
  ON kw_classification_overrides (pesquisa_id, analysis_version);
