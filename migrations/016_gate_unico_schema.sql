-- Migration 016 — Gate único: renomear CPC, avaliacao_json, geo_target_id, status simplificado
-- Idempotente: usa IF EXISTS / IF NOT EXISTS em todos os passos.

-- 1. Renomear colunas CPC em kw_staging
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='kw_staging' AND column_name='cpc_low_brl') THEN
    ALTER TABLE kw_staging RENAME COLUMN cpc_low_brl TO bid_pos5_8_brl;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='kw_staging' AND column_name='cpc_high_brl') THEN
    ALTER TABLE kw_staging RENAME COLUMN cpc_high_brl TO bid_pos1_4_brl;
  END IF;
END $$;

-- 2. Adicionar avaliacao_json em pesquisas
ALTER TABLE pesquisas ADD COLUMN IF NOT EXISTS avaliacao_json JSONB;

-- 3. Corrigir geo_target_id: remover NOT NULL e zerar default incorreto
ALTER TABLE pesquisas ALTER COLUMN geo_target_id DROP NOT NULL;
ALTER TABLE pesquisas ALTER COLUMN geo_target_id SET DEFAULT NULL;

-- 4. Migrar status gate_2_* para nomes sem referência a gate numerado
UPDATE pesquisas SET status = 'classificado' WHERE status = 'gate_2_pending';
UPDATE pesquisas SET status = 'aprovado'     WHERE status = 'gate_2_approved';

-- 5. Atualizar constraint de status em pesquisas
ALTER TABLE pesquisas DROP CONSTRAINT IF EXISTS pesquisas_status_check;
ALTER TABLE pesquisas ADD CONSTRAINT pesquisas_status_check
  CHECK (status IN ('pending_review', 'approved', 'rejected', 'classificado', 'aprovado'));
