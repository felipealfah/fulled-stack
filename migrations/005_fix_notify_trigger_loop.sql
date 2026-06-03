-- Migration 005 — Corrige loop infinito no trigger NOTIFY
--
-- Problema: o trigger 004 dispara em INSERT OR UPDATE WHEN (status='pending').
-- O polling faz rollback de triggered_at=NULL em rows que falharam no POST Multica.
-- Esse UPDATE mantém status='pending', então o trigger re-dispara → NOTIFY → polling
-- tenta de novo → falha → rollback → NOTIFY → loop infinito.
--
-- Correção: dois triggers separados em vez de um INSERT OR UPDATE combinado.
-- PostgreSQL não permite referenciar OLD em WHEN clause de INSERT triggers,
-- então a separação é necessária.
--
-- Casos de uso cobertos:
--   - INSERT status='pending' (fastapi /approve endpoint): NOTIFY emitido ✓
--   - UPDATE status='failed' → 'pending' (retry manual futuro): NOTIFY emitido ✓
--   - UPDATE triggered_at=NULL (rollback polling): trigger NÃO dispara ✓
--
-- Idempotente: DROP TRIGGER IF EXISTS + CREATE TRIGGER

-- Remove trigger combinado da migration 004
DROP TRIGGER IF EXISTS notify_agent_executions ON agent_executions;

-- Trigger 1: INSERT com status='pending'
DROP TRIGGER IF EXISTS notify_agent_executions_insert ON agent_executions;

CREATE TRIGGER notify_agent_executions_insert
AFTER INSERT ON agent_executions
FOR EACH ROW
WHEN (NEW.status = 'pending')
EXECUTE FUNCTION notify_agent_executions_fn();

-- Trigger 2: UPDATE onde status mudou PARA 'pending'
-- (ex: retry manual de task failed — caso futuro)
-- NÃO dispara em rollback de triggered_at (status não muda)
DROP TRIGGER IF EXISTS notify_agent_executions_update ON agent_executions;

CREATE TRIGGER notify_agent_executions_update
AFTER UPDATE ON agent_executions
FOR EACH ROW
WHEN (NEW.status = 'pending' AND OLD.status IS DISTINCT FROM 'pending')
EXECUTE FUNCTION notify_agent_executions_fn();
