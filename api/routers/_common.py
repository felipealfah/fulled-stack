"""Helpers compartilhados entre routers da Stack.

_resolve_projeto: hoje vive em seo_plan.py. Extraído aqui para os routers
novos da Phase 10 (keywords, competitor_audit, backlink_intel, rank_tracking)
não copiarem a mesma implementação 4 vezes.

_pesquisas_do_projeto: composição cross-DB da Fase 35 — devolve as pesquisas do
projeto (Postgres) já no formato que o filtro `= ANY($1::uuid[])` do Supabase consome.

_load_gcp_key: auto-detecta base64 ou JSON puro numa env var de SA GCP.
No .env-prod da VPS as chaves ficam em base64 (evita quebra de quotes/newlines
no Portainer stack.env). No worker/.env local ficam em JSON single-line.

NÃO alterar assinatura sem atualizar seo_plan.py e os routers novos.
"""

import base64
import json
import os
import sys

from fastapi import HTTPException


async def _resolve_projeto(conn, projeto_id: str) -> dict:
    """Resolve UUID string para linha do projeto com id_int_legado.

    Retorna {"id": UUID, "id_int_legado": int | None}.
    Levanta HTTPException(404, "Projeto não encontrado") se UUID não existe.
    Levanta HTTPException(422, ...) se UUID mal-formatado.

    Comportamento idêntico ao helper original de seo_plan.py:26-34.
    """
    try:
        proj = await conn.fetchrow(
            "SELECT id, id_int_legado FROM projetos WHERE id = $1::uuid",
            projeto_id,
        )
    except Exception as e:
        # asyncpg levanta InvalidTextRepresentationError se UUID malformado
        msg = str(e).lower()
        if "invalid input syntax" in msg or "uuid" in msg:
            raise HTTPException(422, "projeto_id não é um UUID válido")
        raise
    if not proj:
        raise HTTPException(404, "Projeto não encontrado")
    return dict(proj)


async def _resolve_projeto_id_int(conn, projeto_id: str) -> int:
    """Resolve UUID string → `id_int_legado` (INT), para tabelas com FK INTEGER.

    Wrapper de `_resolve_projeto` para os routers cujas tabelas mantiveram a FK
    INTEGER depois da migração UUID da Phase 05 (`rank_intel_overrides`,
    `projeto_geo_targets`, `content_pages`).

    404 se o projeto não existe; 422 se o UUID é malformado ou se o projeto foi
    criado depois da Phase 05 e nunca recebeu `id_int_legado`. A mensagem é
    deliberadamente genérica: nomear a tabela aqui colocaria o nome de uma tabela
    migrada na mesma linha da conexão do Postgres, o que o portão estático da
    Fase 35 (e um leitor humano) não consegue distinguir de uma query de verdade.

    Fase 35 / D-02: chamar SEMPRE no pool do Postgres da Stack (`projetos` é camada
    de decisão e não migra). Sem FK cross-DB este é o único controle que impede
    travessia entre projetos no Supabase (T-35-05).
    """
    proj = await _resolve_projeto(conn, projeto_id)
    id_int = proj.get("id_int_legado")
    if id_int is None:
        raise HTTPException(
            422,
            "Projeto sem id_int_legado — a tabela deste endpoint ainda usa FK INTEGER; "
            "rode o backfill da Phase 05 antes de usar este endpoint.",
        )
    return id_int


async def _pesquisas_do_projeto(
    conn_pg,
    projeto_id: str,
    pid_int: int | None,
    statuses: list[str] | None = None,
) -> dict[str, dict]:
    """Resolve as pesquisas do projeto no Postgres da Stack.

    Fase 35 / D-02 — ADR
    Full_AIOS_LEADGEN/inteligence/decisoes/2026-08-29_Migracao_LeadGen_Postgres_Supabase.md

    `pesquisas` é camada de decisão e **não** migrou; `kw_staging` migrou. O JOIN que
    ligava as duas deixou de ser possível, então a condição de projeto passa a ser
    resolvida aqui, e o resultado alimenta o `= ANY($1::uuid[])` do lado Supabase.

    Devolve `{pesquisa_id_str: dict(row)}` com `id`, `papel`, `nicho` e `status` — as
    mesmas colunas que o JOIN fornecia. A chave é o UUID em texto, no formato canônico
    que o `::text` do Postgres também produz do outro lado.

    `statuses=None` significa **sem filtro de status** — e não "nenhum status". Os
    handlers do Gate de Keywords precisam das duas leituras: `skipped_descarta` e
    `pending_restantes` contam sobre TODAS as pesquisas do projeto, enquanto a aprovação
    só alcança as revisáveis. Passar a lista errada muda contagem que o Board lê.

    Chamar SEMPRE no pool do Postgres (`conn_pg`) e SEMPRE antes de tocar o Supabase:
    sem FK cross-DB esta resolução é o único controle que impede travessia entre
    projetos (T-35-05).
    """
    rows = await conn_pg.fetch(
        """SELECT id, papel, nicho, status
             FROM pesquisas
            WHERE (projeto_id_uuid = $1::uuid
                   OR ($2::int IS NOT NULL AND projeto_id = $2::int))
              AND ($3::text[] IS NULL OR status = ANY($3::text[]))""",
        projeto_id,
        pid_int,
        list(statuses) if statuses is not None else None,
    )
    return {str(r["id"]): dict(r) for r in rows}


def _load_gcp_key(env_name: str) -> dict | None:
    """Lê SA GCP de env aceitando base64 OU JSON single-line.

    Ordem: tenta JSON puro primeiro (worker/.env), depois base64 (.env-prod).
    Retorna dict pronto para `service_account.Credentials.from_service_account_info`,
    ou None se env ausente/inválida (com WARN em stderr — não crasha o processo).
    """
    raw = os.environ.get(env_name)
    if not raw:
        print(f"[WARN] {env_name} não configurada — BQ writes desabilitados", file=sys.stderr)
        return None

    raw = raw.strip().strip("'").strip('"')

    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except Exception as e:
            print(f"[WARN] {env_name} JSON inválido: {e}", file=sys.stderr)
            return None

    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        print(f"[WARN] {env_name} não é JSON nem base64 válido: {e}", file=sys.stderr)
        return None
