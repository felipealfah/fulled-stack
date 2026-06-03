-- Schema FullED — Staging Layer
-- Executar no Postgres do VPS antes de subir a API

-- Tabela de pesquisas (cada execução do Research pipeline)
CREATE TABLE IF NOT EXISTS pesquisas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projeto_nome    VARCHAR(100) NOT NULL,
    nicho           VARCHAR(100) NOT NULL,
    cidade          VARCHAR(100) NOT NULL DEFAULT 'Brasília',
    geo_target_id   VARCHAR(20)  NOT NULL DEFAULT '1001773',
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending_review',
    -- pending_review | approved | rejected
    seed_keywords   JSONB,
    kestra_execution_id VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ
);

-- Tabela de keywords no staging (pré-bronze)
CREATE TABLE IF NOT EXISTS kw_staging (
    id                  SERIAL PRIMARY KEY,
    pesquisa_id         UUID NOT NULL REFERENCES pesquisas(id) ON DELETE CASCADE,
    keyword             TEXT NOT NULL,
    avg_monthly_searches INTEGER,
    competition         VARCHAR(20),   -- LOW | MEDIUM | HIGH | UNSPECIFIED
    competition_index   FLOAT,
    cpc_low_brl         FLOAT,
    cpc_high_brl        FLOAT,
    score               FLOAT,         -- 0-100 do keyword_scorer
    go_nogo             VARCHAR(10),   -- GO | NO-GO
    status              VARCHAR(20)    NOT NULL DEFAULT 'pending',
    -- pending | approved | rejected
    board_note          TEXT,          -- nota do Board ao revisar
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kw_staging_pesquisa_id ON kw_staging(pesquisa_id);
CREATE INDEX IF NOT EXISTS idx_kw_staging_status ON kw_staging(status);

-- Tabela de projetos ativos
CREATE TABLE IF NOT EXISTS projetos (
    id              SERIAL PRIMARY KEY,
    projeto_nome    VARCHAR(100) UNIQUE NOT NULL,
    nicho           VARCHAR(100) NOT NULL,
    cidade          VARCHAR(100) NOT NULL DEFAULT 'Brasília',
    status          VARCHAR(30)  NOT NULL DEFAULT 'research',
    -- research | construcao | deploy | monetizacao | manutencao
    pesquisa_id_atual UUID REFERENCES pesquisas(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Trigger para updated_at automático
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER kw_staging_updated_at
    BEFORE UPDATE ON kw_staging
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE TRIGGER projetos_updated_at
    BEFORE UPDATE ON projetos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
