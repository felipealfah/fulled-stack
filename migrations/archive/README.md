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
