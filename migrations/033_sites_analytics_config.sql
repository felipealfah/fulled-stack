-- Migration 033 — Tabela de configuração de analytics por site
-- Centraliza project IDs e tokens do Clarity e GA4 para coleta automatizada.
-- Fonte de verdade: n8n workflows de coleta diária consultam esta tabela.

CREATE TABLE IF NOT EXISTS sites_analytics_config (
    id                  SERIAL PRIMARY KEY,
    site_domain         VARCHAR(255) UNIQUE NOT NULL,
    clarity_project_id  VARCHAR(50),
    clarity_api_token   TEXT,
    ga4_property_id     VARCHAR(50),
    active              BOOLEAN NOT NULL DEFAULT true,
    notas               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sac_active ON sites_analytics_config (active)
    WHERE active = true;

COMMENT ON TABLE  sites_analytics_config IS 'Configuração de analytics por site: Clarity project IDs/tokens e GA4 property IDs. Consultada pelos workflows n8n de coleta diária.';
COMMENT ON COLUMN sites_analytics_config.site_domain       IS 'Domínio do site (ex: mmentulho.com.br)';
COMMENT ON COLUMN sites_analytics_config.clarity_project_id IS 'ID do projeto no Microsoft Clarity (ex: xr4nljougf)';
COMMENT ON COLUMN sites_analytics_config.clarity_api_token  IS 'JWT Bearer token gerado em Settings > API no Clarity (por projeto)';
COMMENT ON COLUMN sites_analytics_config.ga4_property_id    IS 'ID da propriedade GA4 sem prefixo (ex: 546988872 → analytics_546988872 no BQ)';
COMMENT ON COLUMN sites_analytics_config.active             IS 'false = excluído da coleta sem deletar o registro';

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_sites_analytics_config_updated_at ON sites_analytics_config;
CREATE TRIGGER update_sites_analytics_config_updated_at
    BEFORE UPDATE ON sites_analytics_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed inicial com os dois sites ativos
-- clarity_api_token = NULL por padrão; preencher após gerar via Settings > API no Clarity
INSERT INTO sites_analytics_config (site_domain, clarity_project_id, ga4_property_id, notas)
VALUES
    ('mmentulho.com.br',          'xr4nljougf', '546988872', 'Rank & Rent marido de aluguel'),
    ('eomaridodealuguel.com.br',   'xu5rhe229o', '547528510', 'Rank & Rent marido de aluguel EO')
ON CONFLICT (site_domain) DO UPDATE SET
    clarity_project_id = EXCLUDED.clarity_project_id,
    ga4_property_id    = EXCLUDED.ga4_property_id,
    notas              = EXCLUDED.notas,
    updated_at         = NOW();
