-- Migration 017 — competitive_intel direto em kw_staging (sem seo_plan_pages)
-- Idempotente: usa ADD COLUMN IF NOT EXISTS.

ALTER TABLE kw_staging ADD COLUMN IF NOT EXISTS competitive_score   DOUBLE PRECISION;
ALTER TABLE kw_staging ADD COLUMN IF NOT EXISTS difficulty_label    VARCHAR(20);
ALTER TABLE kw_staging ADD COLUMN IF NOT EXISTS top_competitor_url  TEXT;
ALTER TABLE kw_staging ADD COLUMN IF NOT EXISTS intel_json          JSONB;
ALTER TABLE kw_staging ADD COLUMN IF NOT EXISTS intel_updated_at    TIMESTAMPTZ;
