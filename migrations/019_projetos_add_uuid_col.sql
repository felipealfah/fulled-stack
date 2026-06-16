-- Migration 019 — Fase 1/2 da migração UUID: adicionar id_uuid em projetos
-- Idempotente: usa ADD COLUMN IF NOT EXISTS, UPDATE condicional, ALTER ... IF NOT EXISTS.
-- NÃO altera PK, NÃO toca FKs existentes.
-- Contexto: Phase 05 — UUID Canônico de Projetos

-- PASSO 1: Adicionar coluna UUID em projetos (sem DEFAULT fixo — gen_random_uuid() por row)
-- PG17 avalia gen_random_uuid() uma vez por INSERT, não em varredura.
ALTER TABLE projetos
  ADD COLUMN IF NOT EXISTS id_uuid UUID DEFAULT gen_random_uuid();

-- PASSO 2: Backfill mmentulho com UUID canônico do Supabase CRM
-- (gen_random_uuid() já foi aplicado no ADD COLUMN para os demais rows)
-- Usa id_int_legado se existir (pós-migration 021), senão id = 8 (pré-021)
DO $$
BEGIN
  -- Pós-021: id renomeada para id_int_legado — usar essa coluna
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projetos' AND column_name = 'id_int_legado'
  ) THEN
    UPDATE projetos
    SET id_uuid = 'f131ca75-1d73-4e04-a89b-3bb85045a9eb'::uuid
    WHERE id_int_legado = 8
      AND (id_uuid IS NULL OR id_uuid != 'f131ca75-1d73-4e04-a89b-3bb85045a9eb'::uuid);
  ELSE
    -- Pré-021: id ainda é INTEGER
    UPDATE projetos
    SET id_uuid = 'f131ca75-1d73-4e04-a89b-3bb85045a9eb'::uuid
    WHERE id = 8
      AND (id_uuid IS NULL OR id_uuid != 'f131ca75-1d73-4e04-a89b-3bb85045a9eb'::uuid);
  END IF;
END $$;

-- PASSO 3: Garantir NOT NULL e unicidade
-- Primeiro verificar se todos os rows têm id_uuid antes de aplicar NOT NULL
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM projetos WHERE id_uuid IS NULL) THEN
    RAISE EXCEPTION 'id_uuid tem NULL em projetos — backfill incompleto';
  END IF;
END $$;

ALTER TABLE projetos ALTER COLUMN id_uuid SET NOT NULL;

-- PASSO 4: Índice único para id_uuid (futuro PK)
CREATE UNIQUE INDEX IF NOT EXISTS projetos_id_uuid_unique ON projetos(id_uuid);

-- Verificação final (log)
DO $$
DECLARE cnt INTEGER;
BEGIN
  SELECT count(*) INTO cnt FROM projetos WHERE id_uuid IS NOT NULL;
  RAISE NOTICE 'Migration 019 OK — % rows com id_uuid preenchido', cnt;
END $$;
