-- Migration 008 — pesquisas: add papel TEXT CHECK('principal','servico'), servico_slug TEXT
-- Aplicar local: docker exec fullaios-postgres-1 psql -U postgres -d fulled -f /tmp/008_multi_pesquisa.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).

-- 1. Coluna papel (nullable — 'principal' ou 'servico'; NULL = pesquisa não vinculada a projeto)
ALTER TABLE pesquisas
  ADD COLUMN IF NOT EXISTS papel TEXT;

-- 2. CHECK constraint em papel (drop-and-recreate para idempotência)
ALTER TABLE pesquisas
  DROP CONSTRAINT IF EXISTS pesquisas_papel_check;

ALTER TABLE pesquisas
  ADD CONSTRAINT pesquisas_papel_check
  CHECK (papel IN ('principal', 'servico'));

-- 3. Coluna servico_slug (nullable — ex: 'encanamento', 'hidraulica'; só obrigatório quando papel = 'servico')
ALTER TABLE pesquisas
  ADD COLUMN IF NOT EXISTS servico_slug TEXT;
