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
-- NOT VALID: o migrator re-executa TODAS as migrations a cada subida; sem NOT VALID,
-- o replay desta migration quebra quando o banco já tem tipos adicionados por
-- migrations posteriores (ex: 'prospeccao' na 025) — "check constraint is violated
-- by some row". NOT VALID pula a validação das rows existentes mas segue valendo
-- para INSERT/UPDATE novos. A lista vigente é sempre a da última migration que
-- recria o constraint (hoje: 025).
ALTER TABLE projetos
  DROP CONSTRAINT IF EXISTS projetos_tipo_check;

ALTER TABLE projetos
  ADD CONSTRAINT projetos_tipo_check
  CHECK (tipo IN ('rank_rent', 'infoproduto', 'youtube_faceless', 'facebook_faceless'))
  NOT VALID;
