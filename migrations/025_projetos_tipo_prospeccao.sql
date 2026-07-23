-- 025: tipo 'prospeccao' em projetos + vínculo leads_prospeccao → projetos
-- Projeto tipo prospeccao = campanha outbound (nicho + cidade). Leads pertencem à campanha.

-- 1. Novo tipo no CHECK (drop-and-recreate, idempotente — padrão da 007)
-- NOT VALID pelo mesmo motivo da 007: o migrator faz replay de todas as migrations;
-- se uma migration futura adicionar outro tipo, o replay desta não pode quebrar.
-- O check segue valendo para INSERT/UPDATE novos.
ALTER TABLE projetos
  DROP CONSTRAINT IF EXISTS projetos_tipo_check;

ALTER TABLE projetos
  ADD CONSTRAINT projetos_tipo_check
  CHECK (tipo IN ('rank_rent', 'infoproduto', 'youtube_faceless', 'facebook_faceless', 'prospeccao'))
  NOT VALID;

-- 2. Vínculo do lead com a campanha (nullable — leads antigos/avulsos continuam válidos)
ALTER TABLE leads_prospeccao
  ADD COLUMN IF NOT EXISTS projeto_id uuid REFERENCES projetos(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_leads_prospeccao_projeto_id ON leads_prospeccao(projeto_id);
