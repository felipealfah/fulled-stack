-- Migration 018 — adicionar projeto_id FK em pesquisas para suporte multi-pesquisa por projeto
-- Idempotente: usa ADD COLUMN IF NOT EXISTS e CREATE INDEX IF NOT EXISTS.

ALTER TABLE pesquisas ADD COLUMN IF NOT EXISTS projeto_id INTEGER REFERENCES projetos(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_pesquisas_projeto_id ON pesquisas(projeto_id);
