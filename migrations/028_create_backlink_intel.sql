-- Migration 028 — REQ-8-06
-- Cria tabela backlink_intel — destino do PUT /projetos/{uuid}/backlink-intel (plan 02).
-- PK natural: projeto_id UUID FK projetos(id) ON DELETE CASCADE.
-- Uma linha por projeto (upsert idempotente via ON CONFLICT (projeto_id)).
--
-- REVERSIBILIDADE (rollback manual):
--   DROP TABLE IF EXISTS backlink_intel CASCADE;

BEGIN;

CREATE TABLE IF NOT EXISTS backlink_intel (
  projeto_id            uuid PRIMARY KEY REFERENCES projetos(id) ON DELETE CASCADE,
  slug                  text NOT NULL,
  keyword_principal     text,
  generated_at          timestamptz,
  summary               jsonb NOT NULL DEFAULT '{}'::jsonb,
  competitors_analyzed  jsonb NOT NULL DEFAULT '[]'::jsonb,
  opportunities         jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS backlink_intel_slug_idx ON backlink_intel (slug);

COMMIT;
