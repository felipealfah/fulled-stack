-- Migration 030 — Phase 32: KW Management Endpoints
-- Aplicado automaticamente pelo serviço migrator do docker-compose raiz — idempotente.
-- CRÍTICO: NÃO adicionar updated_at em kw_staging — já existe em schema.sql linha 34 com trigger kw_staging_updated_at.
-- Para aplicar local sem stack completa: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/030_kw_mgmt_endpoints.sql
-- Bloco B (Plan 32-03: DELETE cascade) e Bloco C (Plan 32-04: content_pages) serão APENDADOS neste mesmo arquivo.

-- Bloco A — kw_staging.kw_type: adicionar LOCALIDADE e SURPRESA (per KWMGMT-01)
ALTER TABLE kw_staging DROP CONSTRAINT IF EXISTS kw_staging_kw_type_check;
ALTER TABLE kw_staging ADD CONSTRAINT kw_staging_kw_type_check
  CHECK (kw_type IN (
    'principal', 'silo', 'geo', 'descarta',
    'PAGINA_PRINCIPAL', 'SERVICO', 'PAGINA_GEO', 'SECAO', 'DESCARTA',
    'LOCALIDADE', 'SURPRESA'
  )) NOT VALID;

-- Bloco A-2 — pesquisas.deleted_at para soft-delete (per KWMGMT-03, usado no Plan 32-03)
ALTER TABLE pesquisas ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_pesquisas_deleted_at ON pesquisas(deleted_at) WHERE deleted_at IS NOT NULL;

-- Bloco B (Plan 32-03) — CHECK tolerante em projeto_seo_plan_pages.difficulty_label
-- Safety net: aceita valores canônicos LOW/MED/HIGH além dos pt (baixo/médio/alto)
-- para casos de fallback no populate-intel.
ALTER TABLE projeto_seo_plan_pages DROP CONSTRAINT IF EXISTS projeto_seo_plan_pages_difficulty_check;
ALTER TABLE projeto_seo_plan_pages ADD CONSTRAINT projeto_seo_plan_pages_difficulty_check
  CHECK (difficulty_label IN ('baixo', 'médio', 'alto', 'LOW', 'MED', 'HIGH') OR difficulty_label IS NULL) NOT VALID;

-- Bloco C (Plan 32-04) será apendado neste mesmo arquivo pela wave 4 — content_pages expansão.
