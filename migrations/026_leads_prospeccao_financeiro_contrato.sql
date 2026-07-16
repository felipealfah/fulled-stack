-- 026: campos de financeiro, contrato e follow-up em leads_prospeccao (paridade v2 do prospector)

ALTER TABLE leads_prospeccao
  ADD COLUMN IF NOT EXISTS valor_fechado     numeric(10,2),
  ADD COLUMN IF NOT EXISTS manutencao_mensal numeric(10,2),
  ADD COLUMN IF NOT EXISTS pago              boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS contrato_status   text CHECK (contrato_status IN ('enviado', 'assinado')),
  ADD COLUMN IF NOT EXISTS contrato_em       timestamptz,
  ADD COLUMN IF NOT EXISTS followup_em       timestamptz,
  ADD COLUMN IF NOT EXISTS respondeu_em      timestamptz,
  ADD COLUMN IF NOT EXISTS resumo_resposta   text,
  ADD COLUMN IF NOT EXISTS doc_cliente       text,
  ADD COLUMN IF NOT EXISTS end_cliente       text;
