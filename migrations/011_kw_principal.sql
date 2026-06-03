-- Migration 011 — pesquisas: kw_principal_id, kw_principal_locked_at; kw_staging.kw_type: +SERVICO
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/011_kw_principal.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
-- Contexto: kw_principal eleita no Plano SEO (Phase 14); FK para kw_staging(id) adicionada na Phase 14.

-- 1. Colunas para eleição da kw_principal (preenchidas na Phase 14 — Plano SEO)
ALTER TABLE pesquisas
  ADD COLUMN IF NOT EXISTS kw_principal_id INTEGER;

ALTER TABLE pesquisas
  ADD COLUMN IF NOT EXISTS kw_principal_locked_at TIMESTAMPTZ;

-- 2. Expandir kw_staging.kw_type para incluir SERVICO
--    Mantém todos os valores legados e anteriores para compatibilidade total.
ALTER TABLE kw_staging
  DROP CONSTRAINT IF EXISTS kw_staging_kw_type_check;

ALTER TABLE kw_staging
  ADD CONSTRAINT kw_staging_kw_type_check
  CHECK (kw_type IN (
    'principal', 'silo', 'geo', 'descarta',
    'PAGINA_PRINCIPAL', 'SERVICO', 'PAGINA_GEO', 'SECAO', 'DESCARTA'
  ));
