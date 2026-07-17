-- Migration 019b: Tabela competitor_audits
-- Criada fora do sistema de migrations (LEADGEN/worker/scripts/competitor_audit/)
-- Adicionada ao STACK para garantir instalação limpa no VPS.
-- Idempotente: IF NOT EXISTS em tudo.

CREATE TABLE IF NOT EXISTS competitor_audits (
  id                   SERIAL PRIMARY KEY,
  projeto_id           INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  slug                 TEXT NOT NULL,
  keyword_principal    TEXT,
  generated_at         TIMESTAMP,
  competitor_count     INTEGER DEFAULT 0,
  benchmark_word_count INTEGER,
  required_sections    JSONB DEFAULT '[]',
  schema_missing       JSONB DEFAULT '[]',
  geo_pages_benchmark  INTEGER DEFAULT 0,
  trust_gaps           JSONB DEFAULT '[]',
  summary              TEXT,
  competitors_json     JSONB DEFAULT '[]',
  yaml_path            TEXT,
  created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS competitor_audits_projeto_id_idx
  ON competitor_audits (projeto_id);
