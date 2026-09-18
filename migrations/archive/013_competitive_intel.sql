-- Migration 013 — projeto_geo_targets + enriquecimento projeto_seo_plan_pages + histórico intel
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/013_competitive_intel.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
-- Contexto: Phase 15 — Competitive Intel Agent

-- 1. Tabela projeto_geo_targets (regiões alvo do projeto)
CREATE TABLE IF NOT EXISTS projeto_geo_targets (
  id              SERIAL PRIMARY KEY,
  projeto_id      INT NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  nome            VARCHAR(100) NOT NULL,
  tipo            VARCHAR(20),
  ativo           BOOLEAN NOT NULL DEFAULT true,
  volume_estimado INTEGER,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE projeto_geo_targets
  DROP CONSTRAINT IF EXISTS projeto_geo_targets_tipo_check;
ALTER TABLE projeto_geo_targets
  ADD CONSTRAINT projeto_geo_targets_tipo_check
  CHECK (tipo IN ('bairro', 'cidade', 'estado') OR tipo IS NULL);

-- 2. ADD COLUMNS em projeto_seo_plan_pages (snapshot do enriquecimento)
ALTER TABLE projeto_seo_plan_pages
  ADD COLUMN IF NOT EXISTS competitive_score   INTEGER;
ALTER TABLE projeto_seo_plan_pages
  ADD COLUMN IF NOT EXISTS difficulty_label    VARCHAR(20);
ALTER TABLE projeto_seo_plan_pages
  ADD COLUMN IF NOT EXISTS top_competitor_url  TEXT;
ALTER TABLE projeto_seo_plan_pages
  ADD COLUMN IF NOT EXISTS intel_updated_at    TIMESTAMPTZ;

ALTER TABLE projeto_seo_plan_pages
  DROP CONSTRAINT IF EXISTS projeto_seo_plan_pages_difficulty_check;
ALTER TABLE projeto_seo_plan_pages
  ADD CONSTRAINT projeto_seo_plan_pages_difficulty_check
  CHECK (difficulty_label IN ('baixo', 'médio', 'alto') OR difficulty_label IS NULL);

-- 3. Tabela histórico de análises (uma row por execução do agente por página)
CREATE TABLE IF NOT EXISTS projeto_seo_plan_pages_intel (
  id                  SERIAL PRIMARY KEY,
  page_id             INTEGER NOT NULL REFERENCES projeto_seo_plan_pages(id) ON DELETE CASCADE,
  competitive_score   INTEGER,
  difficulty_label    VARCHAR(20),
  top_competitor_url  TEXT,
  intel_data          JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
