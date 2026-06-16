-- Migration 020 — Fase 1/2 migração UUID: propagar id_uuid para FK-tables
-- Idempotente: ADD COLUMN IF NOT EXISTS + UPDATE idempotente (SET ... WHERE IS DISTINCT FROM).
-- Contexto: Phase 05 — UUID Canônico de Projetos
-- Pré-requisito: migration 019 deve ter sido aplicada (projetos.id_uuid NOT NULL).

-- PASSO 1: Adicionar coluna projeto_id_uuid nas 7 tabelas com FK para projetos.id

ALTER TABLE pesquisas
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

ALTER TABLE agent_executions
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

ALTER TABLE competitor_audits
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

ALTER TABLE content_pages
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

ALTER TABLE projeto_geo_targets
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

ALTER TABLE projeto_seo_plan
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

ALTER TABLE rank_intel_overrides
  ADD COLUMN IF NOT EXISTS projeto_id_uuid UUID;

-- PASSO 2: Backfill — propagar UUID a partir do JOIN com projetos
-- UPDATE idempotente: só altera rows onde projeto_id_uuid ainda está errado/NULL
-- Pós-migration 021: projetos.id é UUID, projetos.id_int_legado é INTEGER
-- O JOIN usa id_int_legado para compatibilidade com FK-tables que ainda têm projeto_id INTEGER.
-- Se id_int_legado não existir (estado pré-021), usa id (que seria INTEGER nesse estado).
DO $$
BEGIN
  -- Pós-021: projetos.id é UUID, usar id_int_legado no JOIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'projetos' AND column_name = 'id_int_legado'
  ) THEN
    UPDATE pesquisas t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);

    UPDATE agent_executions t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);

    UPDATE competitor_audits t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);

    UPDATE content_pages t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);

    UPDATE projeto_geo_targets t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);

    UPDATE projeto_seo_plan t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);

    UPDATE rank_intel_overrides t SET projeto_id_uuid = p.id
    FROM projetos p
    WHERE t.projeto_id = p.id_int_legado
      AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id);
  ELSE
    -- Pré-021: projetos.id é INTEGER, usar id_uuid
    UPDATE pesquisas t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);

    UPDATE agent_executions t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);

    UPDATE competitor_audits t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);

    UPDATE content_pages t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);

    UPDATE projeto_geo_targets t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);

    UPDATE projeto_seo_plan t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);

    UPDATE rank_intel_overrides t SET projeto_id_uuid = p.id_uuid
    FROM projetos p WHERE t.projeto_id = p.id AND t.projeto_id IS NOT NULL
      AND (t.projeto_id_uuid IS NULL OR t.projeto_id_uuid IS DISTINCT FROM p.id_uuid);
  END IF;
END $$;

-- PASSO 3: Índices nas FK-tables para queries futuras por UUID
CREATE INDEX IF NOT EXISTS idx_pesquisas_projeto_id_uuid          ON pesquisas(projeto_id_uuid);
CREATE INDEX IF NOT EXISTS idx_agent_executions_projeto_id_uuid   ON agent_executions(projeto_id_uuid);
CREATE INDEX IF NOT EXISTS idx_competitor_audits_projeto_id_uuid  ON competitor_audits(projeto_id_uuid);
CREATE INDEX IF NOT EXISTS idx_content_pages_projeto_id_uuid      ON content_pages(projeto_id_uuid);
CREATE INDEX IF NOT EXISTS idx_projeto_geo_targets_uuid           ON projeto_geo_targets(projeto_id_uuid);
CREATE INDEX IF NOT EXISTS idx_projeto_seo_plan_uuid              ON projeto_seo_plan(projeto_id_uuid);
CREATE INDEX IF NOT EXISTS idx_rank_intel_overrides_uuid          ON rank_intel_overrides(projeto_id_uuid);

-- Verificação final
DO $$
DECLARE
  v_pesquisas_null INTEGER;
  v_agent_null     INTEGER;
BEGIN
  SELECT count(*) INTO v_pesquisas_null
    FROM pesquisas WHERE projeto_id IS NOT NULL AND projeto_id_uuid IS NULL;
  SELECT count(*) INTO v_agent_null
    FROM agent_executions WHERE projeto_id IS NOT NULL AND projeto_id_uuid IS NULL;

  IF v_pesquisas_null > 0 THEN
    RAISE WARNING 'Migration 020: % rows em pesquisas com projeto_id sem uuid', v_pesquisas_null;
  END IF;
  IF v_agent_null > 0 THEN
    RAISE WARNING 'Migration 020: % rows em agent_executions com projeto_id sem uuid', v_agent_null;
  END IF;

  RAISE NOTICE 'Migration 020 OK — projeto_id_uuid propagado para FK-tables';
END $$;
