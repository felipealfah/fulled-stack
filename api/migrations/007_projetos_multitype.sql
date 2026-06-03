-- Migration 007 — projetos: add tipo VARCHAR(30), metadata JSONB, receita_mensal NUMERIC(10,2); CHECK constraint em tipo
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/007_projetos_multitype.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).

-- 1. Coluna tipo (DEFAULT 'rank_rent' garante retrocompatibilidade com rows existentes)
ALTER TABLE projetos
  ADD COLUMN IF NOT EXISTS tipo VARCHAR(30) NOT NULL DEFAULT 'rank_rent';

-- 2. Coluna metadata JSONB (DEFAULT '{}' — nunca NULL)
ALTER TABLE projetos
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

-- 3. Coluna receita_mensal (nullable — preenchida manualmente pelo Board)
ALTER TABLE projetos
  ADD COLUMN IF NOT EXISTS receita_mensal NUMERIC(10,2);

-- 4. CHECK constraint em tipo (drop-and-recreate para idempotência)
ALTER TABLE projetos
  DROP CONSTRAINT IF EXISTS projetos_tipo_check;

ALTER TABLE projetos
  ADD CONSTRAINT projetos_tipo_check
  CHECK (tipo IN ('rank_rent', 'infoproduto', 'youtube_faceless', 'facebook_faceless'));
