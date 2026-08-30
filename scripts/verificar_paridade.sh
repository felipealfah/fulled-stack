#!/usr/bin/env bash
# Confere a paridade das 15 tabelas pré-decisão entre o Postgres da Stack (origem)
# e o schema `leadgen` do Supabase (destino) — Fase 35 / SC-04.
#
#   bash scripts/verificar_paridade.sh          # confere e sai 0 se tudo bate
#   bash scripts/verificar_paridade.sh --rapido # só contagens, pula o checksum linha a linha
#
# Sai 0 apenas se, para TODAS as 15 tabelas:
#   (a) count(*) da origem == count(*) do destino;
#   (b) o checksum MD5 das linhas (ordenado, independente de ordem física) bate;
#   (c) toda sequence do schema `leadgen` está no ponto certo — last_value == MAX(id)
#       da sua tabela (ou sequence nunca chamada, quando a tabela está vazia).
# Qualquer divergência sai 1 com um resumo em pt-BR.
#
# Ambiente exigido (mesmas variáveis do api/tests/conftest.py):
#   DATABASE_URL    → Postgres da Stack. Banco de PRODUÇÃO via túnel SSH — abrir antes
#                     com `bash vps_tunnel.sh -d`, que publica a VPS em localhost:5433.
#   LEADGEN_DB_URL  → Supabase `fahafwvaskiftjbniftw` (Supavisor session pooler, porta 5432).
#
# ADR: Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

set -uo pipefail

# As 15 tabelas de D-02. Lista constante no script — nunca vem de entrada externa (T-35-06).
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

RAPIDO=0
[ "${1:-}" = "--rapido" ] && RAPIDO=1

command -v psql >/dev/null 2>&1 || {
  echo "ERRO: psql não encontrado no PATH. Instale o cliente PostgreSQL." >&2; exit 1; }
[ -n "${DATABASE_URL:-}" ] || {
  echo "ERRO: DATABASE_URL não definida — é o Postgres da Stack (túnel: bash vps_tunnel.sh -d)." >&2; exit 1; }
[ -n "${LEADGEN_DB_URL:-}" ] || {
  echo "ERRO: LEADGEN_DB_URL não definida — é o Supabase, schema leadgen (session pooler, 5432)." >&2; exit 1; }

# extra_float_digits=3 nos dois lados: sem isso o texto de `double precision` pode
# divergir entre servidores e o checksum daria falso negativo.
consultar() { psql "$1" -X -q -v ON_ERROR_STOP=1 -tAc "SET extra_float_digits = 3; $2"; }

divergencias=0

echo "Paridade Postgres da Stack → Supabase (schema leadgen) — 15 tabelas de D-02"
echo "─────────────────────────────────────────────────────────────────────────────"

for t in "${TABELAS[@]}"; do
  n_origem=$(consultar "$DATABASE_URL"   "SELECT count(*) FROM public.${t}")
  n_destino=$(consultar "$LEADGEN_DB_URL" "SELECT count(*) FROM leadgen.${t}")

  if [ -z "$n_origem" ] || [ -z "$n_destino" ]; then
    echo "  ✗ ${t}: falha ao consultar (origem='${n_origem}' destino='${n_destino}')"
    divergencias=$((divergencias + 1)); continue
  fi

  if [ "$n_origem" != "$n_destino" ]; then
    echo "  ✗ ${t}: contagem origem=${n_origem} destino=${n_destino}"
    divergencias=$((divergencias + 1)); continue
  fi

  if [ "$RAPIDO" = "1" ]; then
    echo "  ✓ ${t}: ${n_origem} linhas"
    continue
  fi

  # Checksum linha a linha: cada linha vira texto canônico, o conjunto é ordenado pelo
  # próprio texto (independe da ordem física) e some num único MD5. A lista de colunas é
  # montada por ordinal_position no destino e aplicada aos dois lados, então diferença de
  # ordem física de coluna não produz falso negativo.
  cols=$(consultar "$LEADGEN_DB_URL" \
    "SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
       FROM information_schema.columns
      WHERE table_schema = 'leadgen' AND table_name = '${t}'")
  if [ -z "$cols" ]; then
    echo "  ✗ ${t}: tabela não existe no schema leadgen"
    divergencias=$((divergencias + 1)); continue
  fi

  # ORDER BY ... COLLATE "C" é obrigatório: a ordenação padrão de texto depende do
  # locale do servidor, e origem (Debian) e destino (Supabase) têm collations diferentes.
  # Sem o COLLATE "C" as mesmas linhas concatenam em ordens diferentes e o MD5 diverge —
  # falso negativo em toda tabela com acento, espaço ou hífen no conteúdo.
  md5_sql="SELECT coalesce(md5(string_agg(l, E'\n' ORDER BY l COLLATE \"C\")), 'vazia')
             FROM (SELECT (ROW(${cols}))::text AS l FROM %s.${t}) s"
  # shellcheck disable=SC2059
  h_origem=$(consultar "$DATABASE_URL"   "$(printf "$md5_sql" public)")
  # shellcheck disable=SC2059
  h_destino=$(consultar "$LEADGEN_DB_URL" "$(printf "$md5_sql" leadgen)")

  if [ "$h_origem" != "$h_destino" ]; then
    echo "  ✗ ${t}: ${n_origem} linhas dos dois lados, mas o conteúdo difere"
    echo "      md5 origem=${h_origem}"
    echo "      md5 destino=${h_destino}"
    divergencias=$((divergencias + 1)); continue
  fi

  echo "  ✓ ${t}: ${n_origem} linhas, conteúdo idêntico (md5 ${h_origem:0:12})"
done

echo "─────────────────────────────────────────────────────────────────────────────"
echo "Sequences do schema leadgen (last_value × MAX(id))"

# Sequence atrasada = a primeira escrita nova do pipeline colide de PK. É o modo de
# falha mais caro do corte, por isso entra no mesmo portão de saída.
# O laço é dirigido pelo catálogo de sequences (pg_depend deptype='a' = owned by): descobre
# a tabela E a coluna dona de cada sequence, sem assumir que a coluna se chama `id` (três
# das 15 tabelas não têm `id`). query_to_xml executa o max() dinâmico numa consulta só.
seq_out=$(consultar "$LEADGEN_DB_URL" "
  SELECT s.relname || '|' || COALESCE(pg_sequence_last_value(s.oid)::text, 'nunca-usada')
         || '|' || COALESCE(mx.v::text, 'null')
         || '|' || CASE
                     WHEN mx.v IS NULL OR mx.v = 0                        THEN 'OK-vazia'
                     WHEN pg_sequence_last_value(s.oid) = mx.v            THEN 'OK'
                     ELSE 'DIVERGENTE'
                   END
    FROM pg_class s
    JOIN pg_depend d    ON d.classid = 'pg_class'::regclass
                       AND d.objid = s.oid AND d.deptype = 'a'
    JOIN pg_class t     ON t.oid = d.refobjid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
   CROSS JOIN LATERAL (
     SELECT (xpath('/row/v/text()',
             query_to_xml(format('SELECT max(%I) AS v FROM leadgen.%I', a.attname, t.relname),
                          false, true, '')))[1]::text::bigint AS v
   ) mx
   WHERE s.relkind = 'S' AND s.relnamespace = 'leadgen'::regnamespace
   ORDER BY s.relname")

if [ -z "$seq_out" ]; then
  echo "  ✗ nenhuma sequence encontrada no schema leadgen (esperado: 11)"
  divergencias=$((divergencias + 1))
else
  while IFS='|' read -r nome last mx veredito; do
    [ -z "$nome" ] && continue
    if [ "${veredito#OK}" != "$veredito" ]; then
      echo "  ✓ ${nome}: last_value=${last} max(id)=${mx}"
    else
      echo "  ✗ ${nome}: last_value=${last} mas max(id)=${mx} — a próxima escrita colide de PK"
      divergencias=$((divergencias + 1))
    fi
  done <<< "$seq_out"
fi

echo "─────────────────────────────────────────────────────────────────────────────"
if [ "$divergencias" -eq 0 ]; then
  echo "✓ Paridade completa — 15 tabelas e todas as sequences conferidas."
  exit 0
fi
echo "✗ ${divergencias} divergência(s) encontrada(s) — NÃO prosseguir com o corte." >&2
exit 1
