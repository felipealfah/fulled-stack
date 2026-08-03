-- Migration 032 — Backfill de pesquisas.projeto_id (INT legado) a partir de projeto_id_uuid
--
-- CONTEXTO (bug de produção, 2026-08-03):
-- A migration 020 backfillou projeto_id_uuid a partir do INT legado, mas o caminho
-- inverso nunca foi coberto. Desde então, `POST /pesquisas/` (review.py:123) insere
-- APENAS projeto_id_uuid — deixando projeto_id NULL. E `approve_gate2` (review.py:333)
-- fazia `SET projeto_id = $2` com body.projeto_id vazio, zerando o vínculo INT.
--
-- Consequência: `POST /projetos/{id}/keywords/approve-classified` (keywords.py) filtra
-- por `p.projeto_id = <id_int_legado>` e casava ZERO linhas — retornava HTTP 200 com
-- {"approved": 0} sem erro. Todas as keywords de todo projeto criado pós-UUID ficaram
-- travadas em kw_staging.status='pending', e o rank tracking (que filtra status='approved')
-- coletava zero keywords desses projetos.
--
-- Esta migration repara os dados existentes. O código (review.py + keywords.py) foi
-- corrigido no mesmo commit para manter as duas colunas em sincronia daqui pra frente.
--
-- Idempotente: só toca linhas com projeto_id NULL e projeto_id_uuid preenchido.
-- Aplicado automaticamente pelo serviço migrator do docker-compose raiz.

-- Bloco A — Backfill INT a partir do UUID
UPDATE pesquisas p
   SET projeto_id = proj.id_int_legado
  FROM projetos proj
 WHERE p.projeto_id_uuid = proj.id
   AND p.projeto_id IS NULL
   AND proj.id_int_legado IS NOT NULL;

-- Bloco B — Backfill reverso (defensivo): UUID a partir do INT, caso alguma
-- linha antiga tenha só o INT. Repete a lógica da 020 para linhas novas.
UPDATE pesquisas p
   SET projeto_id_uuid = proj.id
  FROM projetos proj
 WHERE p.projeto_id = proj.id_int_legado
   AND p.projeto_id IS NOT NULL
   AND p.projeto_id_uuid IS NULL;

-- Bloco C — Índice composto para os filtros do endpoint de aprovação
-- (busca por projeto + status da pesquisa em uma tacada).
CREATE INDEX IF NOT EXISTS idx_pesquisas_projeto_uuid_status
  ON pesquisas (projeto_id_uuid, status);

-- Bloco D — Índice para a listagem paginada do Board
-- (GET /projetos/{id}/keywords ordena por avg_monthly_searches DESC).
CREATE INDEX IF NOT EXISTS idx_kw_staging_pesquisa_status
  ON kw_staging (pesquisa_id, status);

-- Verificação pós-aplicação (rodar manualmente):
--   SELECT COUNT(*) FROM pesquisas WHERE projeto_id_uuid IS NOT NULL AND projeto_id IS NULL;
--   -- esperado: 0 (ou apenas projetos sem id_int_legado)
