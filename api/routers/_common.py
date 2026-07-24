"""Helpers compartilhados entre routers da Stack.

_resolve_projeto: hoje vive em seo_plan.py. Extraído aqui para os routers
novos da Phase 10 (keywords, competitor_audit, backlink_intel, rank_tracking)
não copiarem a mesma implementação 4 vezes.

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
