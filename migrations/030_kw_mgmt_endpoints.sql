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

-- Bloco C (Plan 32-04, KWMGMT-02): expandir content_pages para sync estrutural do vault.
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS url TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS titulo TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS meta_description TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS h1 TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS kw_type TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS keyword_primaria TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS sem_volume BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS pesquisa_id UUID;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS papel_pesquisa TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS servico_pai TEXT;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS arquivada BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE content_pages ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

-- FK pesquisa_id -> pesquisas (ON DELETE SET NULL)
ALTER TABLE content_pages DROP CONSTRAINT IF EXISTS content_pages_pesquisa_id_fkey;
ALTER TABLE content_pages ADD CONSTRAINT content_pages_pesquisa_id_fkey
  FOREIGN KEY (pesquisa_id) REFERENCES pesquisas(id) ON DELETE SET NULL NOT VALID;

-- Backfill projeto_id_uuid a partir de id_int_legado
UPDATE content_pages cp
   SET projeto_id_uuid = p.id
  FROM projetos p
 WHERE cp.projeto_id = p.id_int_legado
   AND cp.projeto_id_uuid IS NULL;

-- UNIQUE PARCIAL (projeto_id, url) — coexiste com UNIQUE (projeto_id, page_slug)
DROP INDEX IF EXISTS idx_content_pages_projeto_url_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS idx_content_pages_projeto_url_uniq
  ON content_pages (projeto_id, url)
  WHERE url IS NOT NULL;

-- Index de suporte para queries arquivada=false
CREATE INDEX IF NOT EXISTS idx_content_pages_arquivada
  ON content_pages(projeto_id, arquivada);

-- CHECK expandido em kw_type de content_pages
ALTER TABLE content_pages DROP CONSTRAINT IF EXISTS content_pages_kw_type_check;
ALTER TABLE content_pages ADD CONSTRAINT content_pages_kw_type_check
  CHECK (kw_type IS NULL OR kw_type IN (
    'PAGINA_PRINCIPAL','PAGINA_GEO','LOCALIDADE','SECAO','SURPRESA','DESCARTA','SERVICO'
  )) NOT VALID;
