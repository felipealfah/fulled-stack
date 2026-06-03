-- Migration 015: adiciona multica_issue_id em content_pages
-- Permite que o approve endpoint comente na issue do reviewer para acionar o writer.

ALTER TABLE content_pages
  ADD COLUMN IF NOT EXISTS multica_issue_id TEXT;
