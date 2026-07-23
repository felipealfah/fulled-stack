#!/usr/bin/env bash
# Túnel SSH para o Postgres da VPS — rodar no MacBook antes de usar
# scripts que escrevem no banco (kw-validator, rank-intel, site-builder etc.).
#
#   bash vps_tunnel.sh          # abre o túnel em foreground (Ctrl+C encerra)
#   bash vps_tunnel.sh -d       # abre em background (mata com: pkill -f 'ssh.*5433:')
#
# Depois de aberto, o Postgres da VPS responde em localhost:5433
# (DATABASE_URL nos .env já aponta para localhost:5433).
#
# Configure VPS_SSH abaixo (usuário@host ou alias do ~/.ssh/config):

VPS_SSH="${VPS_SSH:-ubuntu@137.131.139.110}"   # ← ajuste o usuário se não for ubuntu
VPS_KEY="${VPS_KEY:-$HOME/.ssh/fulled_vps}"    # chave dedicada (criada no passo de recuperação)
KEY_OPT=""
[ -f "$VPS_KEY" ] && KEY_OPT="-i $VPS_KEY"
LOCAL_PORT=5433
REMOTE_PORT=5432

# Idempotente: se o túnel já responde em localhost:5433, não abre outro.
# Permite que agentes rodem `bash vps_tunnel.sh -d` sempre, sem checar antes.
if nc -z localhost ${LOCAL_PORT} 2>/dev/null; then
  echo "✓ Túnel já aberto — Postgres da VPS em localhost:${LOCAL_PORT}"
  exit 0
fi

if [ "${1:-}" = "-d" ]; then
  ssh $KEY_OPT -f -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
      -L ${LOCAL_PORT}:localhost:${REMOTE_PORT} "$VPS_SSH" \
    && echo "✓ Túnel aberto em background — Postgres da VPS em localhost:${LOCAL_PORT}"
else
  echo "Túnel: localhost:${LOCAL_PORT} → ${VPS_SSH}:${REMOTE_PORT} (Ctrl+C encerra)"
  ssh $KEY_OPT -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
      -L ${LOCAL_PORT}:localhost:${REMOTE_PORT} "$VPS_SSH"
fi
