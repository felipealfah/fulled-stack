-- Migration 003 — agent_executions: colunas triggered_at, completed_at (TIMESTAMPTZ), error + indice parcial pending
-- Aplicar local: psql -h localhost -U fulled -d fulled -f migrations/003_agent_executions.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
--
-- Pre-requisito: a tabela agent_executions ja foi criada pela migration 001.
-- Esta migration apenas evolui o schema; nao recria nada.

-- 1. Coluna triggered_at — preenchida pelo polling-container ao adquirir lock SKIP LOCKED
ALTER TABLE agent_executions
  ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMPTZ;

-- 2. Coluna error — mensagem curta de erro registrada pelo polling/agentes
--    (mantem error_message original intacto; este e um campo adicional, nao um rename)
ALTER TABLE agent_executions
  ADD COLUMN IF NOT EXISTS error TEXT;

-- 3. Promove completed_at de TIMESTAMP -> TIMESTAMPTZ (idempotente)
--    A migration 001 criou como TIMESTAMP (sem timezone). Para alinhar com triggered_at
--    e evitar bugs de fuso horario, convertemos assumindo UTC. So executa se ainda for
--    TIMESTAMP — evita erro ao rodar a migration pela segunda vez.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'agent_executions'
      AND column_name = 'completed_at'
      AND data_type = 'timestamp without time zone'
  ) THEN
    ALTER TABLE agent_executions
      ALTER COLUMN completed_at TYPE TIMESTAMPTZ
      USING completed_at AT TIME ZONE 'UTC';
  END IF;
END
$$;

-- 4. Indice parcial para o polling: SELECT ... WHERE status='pending' FOR UPDATE SKIP LOCKED
--    Como a esmagadora maioria das rows ficara com status='completed', o indice parcial
--    e ordens de magnitude menor que um indice full em `status`.
CREATE INDEX IF NOT EXISTS idx_agent_executions_pending
  ON agent_executions (status, created_at)
  WHERE status = 'pending';
