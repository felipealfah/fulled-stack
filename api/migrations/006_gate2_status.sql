-- Migration 006 — pesquisas.status: gate_2_pending/gate_2_approved; kw_staging.kw_type: valores PAGINA_*
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/006_gate2_status.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).

-- 1. Expandir kw_staging.kw_type para aceitar valores do kw_validator (PAGINA_PRINCIPAL, PAGINA_GEO, SECAO, DESCARTA)
--    Mantém valores legados (principal, silo, geo, descarta) para compatibilidade com dados existentes.
ALTER TABLE kw_staging
  DROP CONSTRAINT IF EXISTS kw_staging_kw_type_check;

ALTER TABLE kw_staging
  ADD CONSTRAINT kw_staging_kw_type_check
  CHECK (kw_type IN (
    'principal', 'silo', 'geo', 'descarta',
    'PAGINA_PRINCIPAL', 'PAGINA_GEO', 'SECAO', 'DESCARTA'
  ));

-- 2. Expandir pesquisas.status para incluir gate_2_pending e gate_2_approved
--    DROP CONSTRAINT IF EXISTS é seguro: se não houver constraint, não falha.
ALTER TABLE pesquisas
  DROP CONSTRAINT IF EXISTS pesquisas_status_check;

ALTER TABLE pesquisas
  ADD CONSTRAINT pesquisas_status_check
  CHECK (status IN (
    'pending_review', 'approved', 'rejected',
    'gate_2_pending', 'gate_2_approved'
  ));
