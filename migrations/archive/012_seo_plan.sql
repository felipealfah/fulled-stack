-- Migration 012 — projeto_seo_plan + projeto_seo_plan_pages
-- Aplicar local: docker exec fulled-postgres psql -U fulled -d fulled -f /tmp/012_seo_plan.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
-- Contexto: Phase 14 — Plano SEO (eleicao de kw_principal por pesquisa, disparo competitive_intel)

-- 1. Tabela principal do plano SEO (um por projeto)
CREATE TABLE IF NOT EXISTS projeto_seo_plan (
  id          SERIAL PRIMARY KEY,
  projeto_id  INT NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  status      VARCHAR(20) NOT NULL DEFAULT 'rascunho',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE projeto_seo_plan
  DROP CONSTRAINT IF EXISTS projeto_seo_plan_projeto_id_unique;
ALTER TABLE projeto_seo_plan
  ADD CONSTRAINT projeto_seo_plan_projeto_id_unique UNIQUE (projeto_id);

ALTER TABLE projeto_seo_plan
  DROP CONSTRAINT IF EXISTS projeto_seo_plan_status_check;
ALTER TABLE projeto_seo_plan
  ADD CONSTRAINT projeto_seo_plan_status_check
  CHECK (status IN ('rascunho', 'pronto'));

-- 2. Páginas do plano: uma por pesquisa vinculada ao projeto
CREATE TABLE IF NOT EXISTS projeto_seo_plan_pages (
  id              SERIAL PRIMARY KEY,
  plan_id         INT NOT NULL REFERENCES projeto_seo_plan(id) ON DELETE CASCADE,
  pesquisa_id     UUID REFERENCES pesquisas(id) ON DELETE SET NULL,
  kw_principal_id INTEGER REFERENCES kw_staging(id) ON DELETE SET NULL,
  papel           VARCHAR(20),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE projeto_seo_plan_pages
  DROP CONSTRAINT IF EXISTS projeto_seo_plan_pages_plan_pesquisa_unique;
ALTER TABLE projeto_seo_plan_pages
  ADD CONSTRAINT projeto_seo_plan_pages_plan_pesquisa_unique UNIQUE (plan_id, pesquisa_id);

ALTER TABLE projeto_seo_plan_pages
  DROP CONSTRAINT IF EXISTS projeto_seo_plan_pages_papel_check;
ALTER TABLE projeto_seo_plan_pages
  ADD CONSTRAINT projeto_seo_plan_pages_papel_check
  CHECK (papel IN ('principal', 'servico') OR papel IS NULL);

-- 3. FK deferida da Phase 13: pesquisas.kw_principal_id -> kw_staging(id)
--    Migration 011 criou a coluna como INTEGER sem FK; adicionamos aqui.
ALTER TABLE pesquisas
  DROP CONSTRAINT IF EXISTS pesquisas_kw_principal_id_fkey;
ALTER TABLE pesquisas
  ADD CONSTRAINT pesquisas_kw_principal_id_fkey
  FOREIGN KEY (kw_principal_id) REFERENCES kw_staging(id) ON DELETE SET NULL;
