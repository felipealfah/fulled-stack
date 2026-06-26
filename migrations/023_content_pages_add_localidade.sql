-- Migration 023 — content_pages: adicionar 'localidade' ao CHECK de page_type
-- Contexto: Phase 08 — Refatoração SEO — Entidades Independentes + Linkagem Bidirecional
-- Adiciona 'localidade' ao constraint content_pages_page_type_check para suportar
-- páginas de localidade da nova arquitetura v2 (D-01, D-03).
--
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/023_content_pages_add_localidade.sql

ALTER TABLE content_pages
  DROP CONSTRAINT IF EXISTS content_pages_page_type_check;
ALTER TABLE content_pages
  ADD CONSTRAINT content_pages_page_type_check
  CHECK (page_type IN ('home', 'service', 'service_region', 'localidade'));
