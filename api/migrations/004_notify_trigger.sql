-- Migration 004 — Trigger NOTIFY para agent_executions
-- Emite NOTIFY agent_executions_channel em qualquer INSERT ou UPDATE
-- que resulte em status='pending'. Sem payload — polling faz SELECT próprio.
--
-- Aplicar local: psql -h localhost -U fulled -d fulled -f migrations/004_notify_trigger.sql
-- Aplicado automaticamente pelo servico `migrator` do docker-compose raiz (idempotente).
--
-- Idempotente: CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS + CREATE TRIGGER
-- (nao existe CREATE TRIGGER IF NOT EXISTS no PG17)

-- 1. Funcao de trigger — emite NOTIFY no canal agent_executions_channel sem payload
--    PERFORM e o idioma correto dentro de PL/pgSQL (nao bare NOTIFY)
--    RETURN NEW e obrigatorio em triggers AFTER que nao cancelem a operacao
CREATE OR REPLACE FUNCTION notify_agent_executions_fn()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_notify('agent_executions_channel', '');
    RETURN NEW;
END;
$$;

-- 2. Trigger — AFTER INSERT OR UPDATE cobre:
--    - INSERT com status='pending' (fastapi /approve endpoint)
--    - UPDATE status -> 'pending' (retry manual futuro de tasks failed)
--    WHEN (NEW.status = 'pending') e avaliado pelo PG antes de invocar a funcao
--    DROP TRIGGER IF EXISTS e necessario para idempotencia (sem CREATE TRIGGER IF NOT EXISTS no PG)
DROP TRIGGER IF EXISTS notify_agent_executions ON agent_executions;

CREATE TRIGGER notify_agent_executions
AFTER INSERT OR UPDATE ON agent_executions
FOR EACH ROW
WHEN (NEW.status = 'pending')
EXECUTE FUNCTION notify_agent_executions_fn();
