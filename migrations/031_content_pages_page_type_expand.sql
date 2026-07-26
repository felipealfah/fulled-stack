-- Migration 031 — content_pages: expandir CHECK de page_type
-- Adiciona os tipos produzidos pelo seo_plan.json que não estavam no whitelist:
-- geo, servicos, quem-somos, contato, politica
-- Sem estes tipos, o endpoint PUT /seo-plan/pages/sync rejeita 69 de 76 páginas.

ALTER TABLE content_pages
DROP CONSTRAINT IF EXISTS content_pages_page_type_check;

ALTER TABLE content_pages
ADD CONSTRAINT content_pages_page_type_check
CHECK (page_type IN (
    'home',
    'service',
    'service_region',
    'localidade',
    'geo',
    'servicos',
    'quem-somos',
    'contato',
    'politica'
));
