-- Migration 014 — content_pages
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/014_content_pages.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
-- Contexto: Phase 21 — Content Reviewer Agent

CREATE TABLE IF NOT EXISTS content_pages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  projeto_id    INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  page_slug     TEXT NOT NULL,
  page_type     TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'gerado',
  review_report JSONB,
  reviewed_at   TIMESTAMPTZ,
  approved_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(projeto_id, page_slug)
);

ALTER TABLE content_pages
  DROP CONSTRAINT IF EXISTS content_pages_status_check;
ALTER TABLE content_pages
  ADD CONSTRAINT content_pages_status_check
  CHECK (status IN ('gerado', 'revisado', 'aprovado', 'revisar'));

ALTER TABLE content_pages
  DROP CONSTRAINT IF EXISTS content_pages_page_type_check;
ALTER TABLE content_pages
  ADD CONSTRAINT content_pages_page_type_check
  CHECK (page_type IN ('home', 'service', 'service_region'));
