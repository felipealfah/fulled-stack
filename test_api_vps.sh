#!/usr/bin/env bash
# Smoke test da API na VPS (Fase 1) — rodar do MacBook:
#   bash test_api_vps.sh
# Lê STACK_API_KEY do worker/.env do LEADGEN (ou defina no shell).

set -u
API="${FASTAPI_URL:-https://api.fulled.com.br}"
if [ -z "${STACK_API_KEY:-}" ]; then
  STACK_API_KEY=$(grep '^STACK_API_KEY=' /Users/felipefull/Documents/Full_AIOS/Full_AIOS_LEADGEN/worker/.env | cut -d= -f2-)
fi

pass=0; fail=0
check() { # nome, esperado, obtido
  if [ "$2" = "$3" ]; then echo "✓ $1 ($3)"; pass=$((pass+1));
  else echo "✗ $1 — esperado $2, obtido $3"; fail=$((fail+1)); fi
}

echo "API: $API"
echo

code=$(curl -sS -m 15 -o /dev/null -w "%{http_code}" "$API/health")
check "/health público" 200 "$code"

code=$(curl -sS -m 15 -o /dev/null -w "%{http_code}" "$API/auth/status")
check "/auth/status público" 200 "$code"

code=$(curl -sS -m 15 -o /dev/null -w "%{http_code}" "$API/projetos/")
check "/projetos SEM chave → 401" 401 "$code"

code=$(curl -sS -m 15 -o /dev/null -w "%{http_code}" -H "x-api-key: $STACK_API_KEY" "$API/projetos/")
check "/projetos COM x-api-key → 200" 200 "$code"

code=$(curl -sS -m 15 -o /dev/null -w "%{http_code}" -H "x-api-key: chave-errada" "$API/projetos/")
check "chave errada → 401" 401 "$code"

echo
echo "— dados migrados? primeiros projetos:"
curl -sS -m 15 -H "x-api-key: $STACK_API_KEY" "$API/projetos/" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    projs = d if isinstance(d, list) else d.get('projetos', d.get('items', []))
    print(f'  {len(projs)} projetos na API')
    for p in projs[:5]:
        print(f\"  - {p.get('projeto_nome', p.get('nome', '?'))} [{p.get('status', '?')}]\")
except Exception as e:
    print(f'  erro ao parsear: {e}')"

echo
[ $fail -eq 0 ] && echo "✅ TODOS OS TESTES PASSARAM ($pass)" || echo "❌ $fail falha(s), $pass ok"
