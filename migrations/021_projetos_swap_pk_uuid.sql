-- Migration 021 — Fase 2/2 da migração UUID: swap PKs + migração FK constraints
-- ATENÇÃO: esta migration é IRREVERSÍVEL — renomeia a PK INTEGER para id_int_legado.
-- Pré-requisito: migration 019 (id_uuid NOT NULL UNIQUE) + migration 020 (projeto_id_uuid nas FK-tables).
-- Pré-requisito: plan 05-03 (FastAPI POST /projetos) deve estar usando id_uuid.
-- Contexto: Phase 05 — UUID Canônico de Projetos

-- Idempotente: verifica se o swap já foi feito (id já é UUID) antes de executar
DO $$
DECLARE
  v_id_type TEXT;
  v_null_count INTEGER;
BEGIN
  SELECT data_type INTO v_id_type
    FROM information_schema.columns
    WHERE table_name = 'projetos' AND column_name = 'id';

  -- Se id já é UUID, o swap já foi feito — skip silencioso
  IF v_id_type = 'uuid' THEN
    RAISE NOTICE 'Migration 021 já aplicada (projetos.id já é uuid) — skip';
    RETURN;
  END IF;

  -- Verificação pré-execução (só quando id ainda é INTEGER)
  SELECT count(*) INTO v_null_count
    FROM pesquisas WHERE projeto_id IS NOT NULL AND projeto_id_uuid IS NULL;
  IF v_null_count > 0 THEN
    RAISE EXCEPTION 'pesquisas tem % rows com projeto_id sem uuid — rodar migration 020 primeiro', v_null_count;
  END IF;

  SELECT count(*) INTO v_null_count
    FROM agent_executions WHERE projeto_id IS NOT NULL AND projeto_id_uuid IS NULL;
  IF v_null_count > 0 THEN
    RAISE EXCEPTION 'agent_executions tem % rows com projeto_id sem uuid — rodar migration 020 primeiro', v_null_count;
  END IF;

  -- PASSO A: DROP FK constraints INTEGER nas tabelas filhas
  ALTER TABLE pesquisas            DROP CONSTRAINT IF EXISTS pesquisas_projeto_id_fkey;
  ALTER TABLE agent_executions     DROP CONSTRAINT IF EXISTS agent_executions_projeto_id_fkey;
  ALTER TABLE competitor_audits    DROP CONSTRAINT IF EXISTS competitor_audits_projeto_id_fkey;
  ALTER TABLE content_pages        DROP CONSTRAINT IF EXISTS content_pages_projeto_id_fkey;
  ALTER TABLE projeto_geo_targets  DROP CONSTRAINT IF EXISTS projeto_geo_targets_projeto_id_fkey;
  ALTER TABLE projeto_seo_plan     DROP CONSTRAINT IF EXISTS projeto_seo_plan_projeto_id_fkey;
  ALTER TABLE rank_intel_overrides DROP CONSTRAINT IF EXISTS rank_intel_overrides_projeto_id_fkey;
  ALTER TABLE pesquisas            DROP CONSTRAINT IF EXISTS fk_pesquisas_projeto;
  ALTER TABLE agent_executions     DROP CONSTRAINT IF EXISTS fk_agent_executions_projeto;

  -- PASSO B: DROP PK antiga (INTEGER)
  ALTER TABLE projetos DROP CONSTRAINT IF EXISTS projetos_pkey;

  -- PASSO C: Remover DEFAULT serial antes de renomear
  ALTER TABLE projetos ALTER COLUMN id DROP DEFAULT;

  -- PASSO D: Renomear colunas em projetos
  ALTER TABLE projetos RENAME COLUMN id TO id_int_legado;
  ALTER TABLE projetos RENAME COLUMN id_uuid TO id;

  -- PASSO E: Adicionar PK UUID
  ALTER TABLE projetos ADD PRIMARY KEY (id);

  -- PASSO F: FK UUID nas 7 tabelas filhas
  ALTER TABLE pesquisas
    ADD CONSTRAINT pesquisas_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE SET NULL;
  ALTER TABLE agent_executions
    ADD CONSTRAINT agent_executions_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE SET NULL;
  ALTER TABLE competitor_audits
    ADD CONSTRAINT competitor_audits_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE CASCADE;
  ALTER TABLE content_pages
    ADD CONSTRAINT content_pages_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE CASCADE;
  ALTER TABLE projeto_geo_targets
    ADD CONSTRAINT projeto_geo_targets_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE CASCADE;
  ALTER TABLE projeto_seo_plan
    ADD CONSTRAINT projeto_seo_plan_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE CASCADE;
  ALTER TABLE rank_intel_overrides
    ADD CONSTRAINT rank_intel_overrides_projeto_id_uuid_fkey
    FOREIGN KEY (projeto_id_uuid) REFERENCES projetos(id) ON DELETE CASCADE;

  -- PASSO G: DEFAULT gen_random_uuid()
  ALTER TABLE projetos ALTER COLUMN id SET DEFAULT gen_random_uuid();

  RAISE NOTICE 'Migration 021 OK — projetos.id agora é UUID';
END $$;

-- Verificação pós-commit
DO $$
DECLARE
  tipo TEXT;
BEGIN
  SELECT data_type INTO tipo
    FROM information_schema.columns
    WHERE table_name = 'projetos' AND column_name = 'id';
  IF tipo != 'uuid' THEN
    RAISE EXCEPTION 'FALHA: projetos.id tipo é %, esperado uuid', tipo;
  END IF;
  RAISE NOTICE 'Migration 021 OK — projetos.id agora é UUID';
END $$;
