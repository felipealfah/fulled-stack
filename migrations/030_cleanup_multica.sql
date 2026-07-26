-- Migration 030 — Remoção de colunas Multica (arquitetura descontinuada)
-- Idempotente: usa DROP COLUMN IF EXISTS.
-- Contexto: migrations 010 (multica_project_id) e 015 (multica_issue_id) foram removidas
-- do repo pois o Multica foi descontinuado e as colunas não têm referências no código.
-- Esta migration limpa os bancos de dados existentes que já tinham essas colunas aplicadas.

ALTER TABLE projetos
  DROP COLUMN IF EXISTS multica_project_id;

ALTER TABLE content_pages
  DROP COLUMN IF EXISTS multica_issue_id;
