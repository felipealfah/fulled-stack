-- Migration 035 — Ponto de não-retorno da Fase 35: derruba no Postgres STACK as 15
-- tabelas pré-decisão do LeadGen que agora vivem no Supabase `fahafwvaskiftjbniftw`,
-- schema `leadgen`. A partir daqui a única cópia desses dados é o Supabase.
-- ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md
--
-- Ordem: filhas antes das pais (projeto_seo_plan_pages_intel → ... → projeto_seo_plan).
-- CASCADE cobre as FKs internas às 15; as FKs que apontam para fora (projetos, pesquisas
-- — tabelas de decisão, D-03) são as únicas coisas que o CASCADE remove nessas duas
-- tabelas, nunca as tabelas em si.
--
-- Esta migration NÃO PODE mencionar projetos, pesquisas, agent_executions ou
-- leads_prospeccao em nenhuma instrução — são as tabelas de decisão que D-03 mantém
-- no Postgres. O bloco de verificação ao final garante isso.

DROP TABLE IF EXISTS projeto_seo_plan_pages_intel CASCADE;
DROP TABLE IF EXISTS projeto_seo_plan_pages       CASCADE;
DROP TABLE IF EXISTS projeto_seo_plan             CASCADE;
DROP TABLE IF EXISTS kw_staging                   CASCADE;
DROP TABLE IF EXISTS kw_classification_overrides  CASCADE;
DROP TABLE IF EXISTS kw_scorecard                 CASCADE;
DROP TABLE IF EXISTS scorecard_overrides          CASCADE;
DROP TABLE IF EXISTS competitor_audits            CASCADE;
DROP TABLE IF EXISTS backlink_intel                CASCADE;
DROP TABLE IF EXISTS content_pages                CASCADE;
DROP TABLE IF EXISTS ranking_dashboard_cache       CASCADE;
DROP TABLE IF EXISTS ranking_history_cache         CASCADE;
DROP TABLE IF EXISTS sites_analytics_config        CASCADE;
DROP TABLE IF EXISTS rank_intel_overrides          CASCADE;
DROP TABLE IF EXISTS projeto_geo_targets           CASCADE;

-- Verificação pós-DROP: as 4 tabelas de decisão de D-03 continuam de pé.
DO $$
DECLARE
  faltando TEXT;
BEGIN
  SELECT string_agg(t, ', ') INTO faltando
  FROM unnest(ARRAY['projetos', 'pesquisas', 'agent_executions', 'leads_prospeccao']) AS t
  WHERE to_regclass('public.' || t) IS NULL;

  IF faltando IS NOT NULL THEN
    RAISE EXCEPTION 'Migration 035 FALHOU: tabela(s) de decisão sumiram: %', faltando;
  END IF;

  RAISE NOTICE 'Migration 035 OK — 15 tabelas pré-decisão derrubadas, as 4 tabelas de decisão continuam intactas';
END $$;
