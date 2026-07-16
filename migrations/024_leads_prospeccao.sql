-- 024: Leads da operação outbound (Full_AIOS_PROSPECTOR)
-- Funil: novo → redesenhado → publicado → proposta_enviada → negociacao → fechado | perdido | inquilino_potencial
-- (descartado = reprovado na qualificação; guardado para não reavaliar no próximo ciclo)

CREATE TABLE IF NOT EXISTS leads_prospeccao (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nome             text NOT NULL,
  slug             text NOT NULL UNIQUE,
  nicho            text NOT NULL,
  cidade           text NOT NULL,
  nota             numeric(2,1),
  n_avaliacoes     integer,
  telefone         text,
  email            text,
  site_url         text,
  motivo_site_ruim text,
  url_preview      text,
  status           text NOT NULL DEFAULT 'novo'
                     CHECK (status IN ('novo', 'descartado', 'redesenhado', 'publicado',
                                       'proposta_enviada', 'negociacao', 'fechado',
                                       'perdido', 'inquilino_potencial')),
  motivo_descarte  text,
  notas            text,
  proposta_em      timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_prospeccao_status ON leads_prospeccao(status);
CREATE INDEX IF NOT EXISTS idx_leads_prospeccao_nicho_cidade ON leads_prospeccao(nicho, cidade);
CREATE INDEX IF NOT EXISTS idx_leads_prospeccao_created_at ON leads_prospeccao(created_at DESC);

-- Dedup na prospecção: mesmo negócio na mesma cidade não entra duas vezes
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_prospeccao_nome_cidade
  ON leads_prospeccao (lower(nome), lower(cidade));
