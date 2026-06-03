-- Migration 010 — projetos: coluna multica_project_id para link com Multica board
-- Aplicar local: psql -h localhost -U fulled -d fulled -f migrations/010_multica_project_id.sql
-- Aplicado automaticamente pelo servico migrator do docker-compose raiz (idempotente).
-- Contexto: Postgres e fonte de verdade; multica_project_id e salvo apos criacao no Multica.

ALTER TABLE projetos
  ADD COLUMN IF NOT EXISTS multica_project_id UUID;
