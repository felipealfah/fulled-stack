# Migrations arquivadas

Arquivos aqui **não são aplicados** pelo migrator — o entrypoint em `docker-compose.yml`
itera só `/migrations/*.sql` (glob não recursivo), e esta pasta fica fora desse caminho.

Nunca editar o conteúdo de um arquivo arquivado — mover para cá é a única mudança feita,
o SQL original fica intacto para referência/histórico.

## 004_rank_intel_overrides.sql

Arquivada em 2026-09-18. `CREATE TABLE ... projeto_id INTEGER REFERENCES projetos(id)`
nunca completou em nenhum ambiente com o schema atual — `projetos.id` é UUID desde a
Phase 05 do LEADGEN, e o `IF NOT EXISTS` não protege porque o `CREATE TABLE` falha antes
de existir. A tabela `rank_intel_overrides` também foi uma das 15 migradas para o
Supabase e derrubadas do Postgres na Fase 35 (`035_drop_tabelas_migradas_supabase.sql`)
— não deveria mais existir aqui de qualquer forma.

Como o migrator roda com `set -e`, essa falha bloqueava TODAS as migrations seguintes
(005 em diante) de rodar pelo mecanismo automático desde que este arquivo passou a
falhar — motivo real de arquivar em vez de só consertar a FK.

## 012_seo_plan.sql, 013_competitive_intel.sql, 014_content_pages.sql, 019b_create_competitor_audits.sql

Arquivadas em 2026-09-18, mesmo motivo do 004: `projeto_id INTEGER/INT REFERENCES
projetos(id)` incompatível com `projetos.id` UUID. Confirmado por auditoria completa
(`grep -rn "REFERENCES projetos" migrations/*.sql`) cruzada com a lista de tabelas da
Fase 35 (`035_drop_tabelas_migradas_supabase.sql`) — as 4 criam exatamente tabelas que
essa fase já decidiu mover para o Supabase e derrubar do Postgres:
`projeto_seo_plan`, `projeto_seo_plan_pages`, `projeto_seo_plan_pages_intel`,
`projeto_geo_targets`, `content_pages`, `competitor_audits`.

Achado ao vivo: `012_seo_plan.sql` travou o migrator numa segunda tentativa de deploy
(mesma classe de erro do 004), depois de já ter passado por 005-011 com sucesso.
Auditoria evitou repetir o incidente uma terceira vez para 013/014/019b, que teriam
falhado do mesmo jeito em sequência.

Migrations não afetadas por este padrão (confirmado por leitura): `009` e `018`
também referenciam `projetos(id)` mas via `ADD COLUMN IF NOT EXISTS` numa coluna que
já existe na base viva — o `IF NOT EXISTS` pula o `ALTER TABLE` inteiro (incluindo a
FK) antes de tentar criá-la, então não erram. `021`, `025`, `028` referenciam
`projeto_id_uuid`/`projeto_id uuid` — já no tipo certo, sem conflito.
