#!/usr/bin/env bash
# Carrega as 15 tabelas pré-decisão do Postgres da Stack para o schema `leadgen`
# do Supabase — Fase 35 / SC-04. Re-executável: TRUNCATE + recarga, nunca duplica linha.
#
#   bash scripts/migrar_leadgen_supabase.sh              # aborta: exige confirmação
#   bash scripts/migrar_leadgen_supabase.sh --confirmar  # apaga o destino e recarrega
#
# APAGA DADOS DO DESTINO. A origem (Postgres da Stack) permanece intacta até a
# migration 034_drop_tabelas_migradas_supabase.sql, então a carga é sempre repetível.
#
# Ambiente exigido:
#   DATABASE_URL    → Postgres da Stack. Banco de PRODUÇÃO via túnel SSH — abrir antes
#                     com `bash vps_tunnel.sh -d`, que publica a VPS em localhost:5433.
#   LEADGEN_DB_URL  → Supabase `fahafwvaskiftjbniftw` (Supavisor session pooler, porta 5432).
#
# Por que `\copy` CSV e não `pg_dump`: o pg_dump do host é 15.13 e recusa o servidor
# 17.10; e o pg_dump do container `fulled-postgres` não alcança o túnel SSH, que faz
# bind só em 127.0.0.1 do Mac (achado do Plan 35-01). O CLIENTE psql 15 conversa
# normalmente com servidor 17, e CSV é agnóstico de versão — preserva JSONB, NULL vs.
# string vazia e newlines embutidos.
#
# ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

set -uo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# As 15 tabelas de D-02, na ordem de carga. Lista constante no script — nunca vem de
# entrada externa (T-35-06). A ordem respeita as FKs internas ao schema leadgen:
# kw_staging e projeto_seo_plan antes de projeto_seo_plan_pages, que vem antes de
# projeto_seo_plan_pages_intel.
TABELAS=(
  kw_staging
  kw_scorecard
  kw_classification_overrides
  scorecard_overrides
  competitor_audits
  backlink_intel
  projeto_seo_plan
  projeto_seo_plan_pages
  projeto_seo_plan_pages_intel
  content_pages
  ranking_dashboard_cache
  ranking_history_cache
  sites_analytics_config
  rank_intel_overrides
  projeto_geo_targets
)

# ── Guardas ──────────────────────────────────────────────────────────────────
if [ "${1:-}" != "--confirmar" ]; then
  echo "Este script APAGA as 15 tabelas do schema leadgen no Supabase e as recarrega"
  echo "a partir do Postgres da Stack. Nada foi tocado."
  echo
  echo "Para executar de verdade:"
  echo "    bash scripts/migrar_leadgen_supabase.sh --confirmar"
  exit 1
fi

command -v psql >/dev/null 2>&1 || {
  echo "ERRO: psql não encontrado no PATH. Instale o cliente PostgreSQL." >&2; exit 1; }
[ -n "${DATABASE_URL:-}" ] || {
  echo "ERRO: DATABASE_URL não definida — é o Postgres da Stack (túnel: bash vps_tunnel.sh -d)." >&2; exit 1; }
[ -n "${LEADGEN_DB_URL:-}" ] || {
  echo "ERRO: LEADGEN_DB_URL não definida — é o Supabase, schema leadgen (session pooler, 5432)." >&2; exit 1; }

# Os CSVs carregam segredo (sites_analytics_config.clarity_api_token é um JWT Bearer do
# Microsoft Clarity). Ficam num diretório temporário fora do repo, com permissão 700, e
# são apagados na saída — inclusive em erro ou Ctrl+C (T-35-02b).
DUMP="$(mktemp -d "${TMPDIR:-/tmp}/fase35-carga.XXXXXX")"
chmod 700 "$DUMP"
trap 'rm -rf "$DUMP"' EXIT INT TERM

origem()  { psql "$DATABASE_URL"   -X -q -v ON_ERROR_STOP=1 "$@"; }
destino() { psql "$LEADGEN_DB_URL" -X -q -v ON_ERROR_STOP=1 "$@"; }

# ── 1. TRUNCATE do destino, numa transação ───────────────────────────────────
# Todas as 15 juntas no mesmo comando: é o que permite truncar tabelas que se
# referenciam entre si dentro do schema leadgen sem CASCADE.
lista_qualificada=$(printf 'leadgen.%s, ' "${TABELAS[@]}"); lista_qualificada=${lista_qualificada%, }
echo "→ Limpando o destino (TRUNCATE das 15 tabelas em uma transação)…"
destino -c "BEGIN; TRUNCATE ${lista_qualificada}; COMMIT;" >/dev/null || {
  echo "ERRO: TRUNCATE falhou — nada foi carregado." >&2; exit 1; }

# ── 2. Export CSV da origem + import no destino, tabela a tabela ─────────────
# A lista de colunas é montada por ordinal_position e aplicada NOS DOIS lados, então
# uma eventual diferença de ordem física de coluna não corrompe a carga.
for t in "${TABELAS[@]}"; do
  cols=$(destino -tAc "SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
                         FROM information_schema.columns
                        WHERE table_schema = 'leadgen' AND table_name = '${t}'")
  if [ -z "$cols" ]; then
    echo "ERRO: tabela leadgen.${t} não existe no destino — aplique as migrations antes." >&2
    exit 1
  fi

  origem -c "\\copy (SELECT ${cols} FROM public.${t}) TO '${DUMP}/${t}.csv' WITH (FORMAT csv)" \
    >/dev/null || { echo "ERRO: export de public.${t} falhou." >&2; exit 1; }

  destino -c "\\copy leadgen.${t} (${cols}) FROM '${DUMP}/${t}.csv' WITH (FORMAT csv)" \
    >/dev/null || { echo "ERRO: carga de leadgen.${t} falhou." >&2; exit 1; }

  n=$(destino -tAc "SELECT count(*) FROM leadgen.${t}")
  echo "  ✓ ${t}: ${n} linhas"
done

# ── 3. Reset das sequences ───────────────────────────────────────────────────
# Sem isto, a primeira escrita nova do pipeline (/kw-validator) colide de PK. O laço é
# dirigido pelo CATÁLOGO de sequences (pg_depend deptype='a' = owned by), não pela lista
# de tabelas: assim ele descobre sozinho a tabela e a COLUNA dona de cada sequence e não
# assume que toda tabela tem `id` — três das 15 (backlink_intel, ranking_dashboard_cache,
# ranking_history_cache) não têm. Nome de sequence, tabela e coluna vêm todos do próprio
# Postgres, nunca de concatenação de entrada externa (T-35-06).
echo "→ Reposicionando as sequences do schema leadgen…"
destino -q -c "
DO \$\$
DECLARE
  r   record;
  mx  bigint;
BEGIN
  FOR r IN
    SELECT s.oid::regclass AS seq, t.relname AS tabela, a.attname AS coluna
      FROM pg_class s
      JOIN pg_depend d   ON d.classid = 'pg_class'::regclass
                        AND d.objid = s.oid AND d.deptype = 'a'
      JOIN pg_class t    ON t.oid = d.refobjid
      JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
     WHERE s.relkind = 'S' AND s.relnamespace = 'leadgen'::regnamespace
     ORDER BY t.relname
  LOOP
    EXECUTE format('SELECT COALESCE(max(%I), 0) FROM leadgen.%I', r.coluna, r.tabela) INTO mx;
    -- is_called = (mx > 0): tabela vazia deixa a sequence intocada em 1, sem queimar o id 1.
    PERFORM setval(r.seq, GREATEST(mx, 1), mx > 0);
  END LOOP;
END
\$\$;" >/dev/null || { echo "ERRO: reset das sequences falhou." >&2; exit 1; }
echo "  ✓ sequences reposicionadas"

# ── 4. Paridade (o portão de saída real) ─────────────────────────────────────
echo
bash "${AQUI}/verificar_paridade.sh"
codigo=$?
if [ "$codigo" -eq 0 ]; then
  echo
  echo "✓ Carga concluída com paridade verificada."
fi
exit "$codigo"
