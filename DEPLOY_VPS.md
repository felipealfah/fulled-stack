# Deploy da Stack na VPS (GitHub + Portainer)

**Fase 1 do plano de migração** (`Full_AIOS_LEADGEN/inteligence/PLANO_Migracao_VPS_n8n.md`).
Compose de produção: `docker-compose.prod.yml` (raiz deste repo).

---

## 1. Preparar o repositório local (rodar no MacBook, dentro de Full_AIOS_STACK)

```bash
cd /Users/felipefull/Documents/Full_AIOS/Full_AIOS_STACK

# 1a. Limpar locks residuais da sessão Cowork de 2026-07-16
rm -f .git/index.lock frontend/.git/index.lock

# 1b. CRÍTICO — absorver o repo git aninhado do frontend.
# Hoje `frontend` está trackeado como gitlink (160000) SEM .gitmodules:
# no GitHub ele subiria VAZIO e o build no Portainer falharia.
rm -rf frontend/.git
git rm --cached frontend
git add frontend/

# 1c. Conferir que nenhum secret vai no commit
git check-ignore .env && echo ".env ignorado ✓"
git add -A
git status   # revisar: NÃO deve aparecer .env

# 1d. Commit
git commit -m "feat: auth no dashboard + compose de produção para VPS/Portainer

- Tela de login + middleware de auth (AUTH_ENABLED, Bearer + x-api-key)
- docker-compose.prod.yml (sem bind mount do Mac, backup diário, portas por env)
- docker-compose.vps.yml descontinuado (continha secrets hardcoded — rotacionar)"
```

## 2. Criar o repositório no GitHub (PRIVADO) e push

```bash
# Com GitHub CLI (gh auth login se necessário):
gh repo create fulled-stack --private --source=. --remote=origin --push

# OU manualmente: criar repo privado "fulled-stack" em github.com/new e:
git remote add origin git@github.com:SEU_USUARIO/fulled-stack.git
git push -u origin master
```

> Repo **privado** — contém schema do negócio e lógica da operação. Secrets não sobem (.env ignorado), mas o repo não é público.

## 3. Portainer — criar a Stack a partir do Git

1. Portainer → **Stacks → Add stack → Repository**
2. **Repository URL:** `https://github.com/SEU_USUARIO/fulled-stack`
3. **Authentication:** ON → username = seu usuário, password = **Personal Access Token** (github.com → Settings → Developer settings → Fine-grained token, só leitura de conteúdo desse repo)
4. **Compose path:** `docker-compose.prod.yml`
5. **Environment variables** (ver §4)
6. Deploy. O Portainer clona, builda `api/` e `frontend/` e sobe os 5 serviços.

> Re-deploy após push: botão **Pull and redeploy** na stack (ou habilitar GitOps polling).

## 4. Variáveis de ambiente no Portainer

| Variável | Valor | Nota |
|---|---|---|
| `POSTGRES_PASSWORD` | senha FORTE nova | NÃO reutilizar `FullED2026!` (estava versionada — comprometida) |
| `AUTH_ENABLED` | `true` | default do prod já é true |
| `DASHBOARD_USER` | `felipe@fulled.com.br` | |
| `DASHBOARD_PASSWORD` | senha do login | rotacionar a que circulou no chat de 2026-07-16 |
| `AUTH_SECRET` | string aleatória longa | `openssl rand -base64 48` |
| `STACK_API_KEY` | string aleatória | `openssl rand -base64 32` — scripts usarão no header `x-api-key` |
| `FRONTEND_PORT` | `3001` (ou outra livre) | |
| `API_PORT` | `8000` (ou outra livre) | |
| `POSTGRES_PORT` | `5432` | ⚠️ se a stack antiga `fulled-data` (pgvector) estiver rodando na VPS, ela usa 5434 — confira portas livres com `docker ps` |
| `GCP_SC_KEY` | JSON da SA (se usar BQ na VPS) | opcional na Fase 1 |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | opcional (sync CRM) |

## 5. HTTPS — reaproveitar o Caddy existente da VPS

A VPS já tem Caddy + rede `proxy_net` (*.fulled.com.br). Duas opções:

**A (recomendada): domínio + Caddy.** Adicionar ao Caddyfile:
```
painel.fulled.com.br {
    reverse_proxy fulled-frontend:80
}
```
e conectar o frontend à rede do proxy (no Portainer: container fulled-frontend → Join network `proxy_net`, ou adicionar a network no compose). DNS: A record `painel` → IP da VPS. O Caddy emite o certificado sozinho. Com isso, **não exponha** `FRONTEND_PORT` publicamente (firewall).

**B (provisória):** acessar por `http://IP_DA_VPS:3001` **apenas com firewall restringindo ao seu IP** — login sem TLS em rede aberta = credencial em texto puro.

Firewall mínimo (Oracle Cloud security list + ufw): liberar 443/80 (Caddy), restringir 5432 e 9443 (Portainer) ao seu IP.

## 6. Migrar os dados (Mac → VPS)

```bash
# No Mac (stack local rodando) — congelar operações durante o dump:
docker exec fulled-postgres pg_dump -U fulled -d fulled -Fc -f /tmp/fulled.dump
docker cp fulled-postgres:/tmp/fulled.dump ./fulled.dump
scp fulled.dump usuario@IP_DA_VPS:/tmp/

# Na VPS (após a stack do Portainer subir e o migrator completar):
docker cp /tmp/fulled.dump fulled-postgres:/tmp/
docker exec fulled-postgres pg_restore -U fulled -d fulled --clean --if-exists /tmp/fulled.dump
docker restart fulled-fastapi
```

## 7. Reapontar o MacBook para a VPS

Nos `.env` locais (LEADGEN `worker/.env`, PROSPECTOR `worker/.env`):
```
DATABASE_URL=postgres://fulled:NOVA_SENHA@IP_DA_VPS:5432/fulled
FASTAPI_URL=https://painel.fulled.com.br/api    # ou http://IP:8000 na opção B
FULLED_API_URL=https://painel.fulled.com.br/api
STACK_API_KEY=<mesmo valor do Portainer>
```

> **Pendência conhecida (checklist Fase 1, item 5):** com `AUTH_ENABLED=true`, os scripts que chamam a API (kw-validator SECTION_*, seo_architect, prospectar_api, prospeccao_leads) precisam enviar o header `x-api-key`. Adicionar aos clients httpx desses scripts na virada — até lá, scripts que só usam `DATABASE_URL` (conexão direta ao Postgres) não são afetados.

## 8. Verificação pós-deploy

- [ ] `https://painel.fulled.com.br/api/health` → `{"status":"ok"}` (sem auth)
- [ ] Dashboard redireciona para `/login`; login funciona; "Sair" funciona
- [ ] API sem token → 401; com `x-api-key` → 200
- [ ] Dados migrados: projetos/pesquisas aparecem no dashboard
- [ ] Backup: `docker exec fulled-backup ls /backups` após as 03:00 (ou dispare um dump manual) + **1 teste de restore**
- [ ] Stack local do Mac desligada (`docker compose down`) para não haver dois estados
- [ ] Registrar ADR da execução em `Full_AIOS_LEADGEN/inteligence/decisoes/`

---
*Gerado em 2026-07-16 — Fase 1 do plano de migração VPS.*
