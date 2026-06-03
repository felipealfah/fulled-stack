"""Cliente HTTP async para a API do Multica (best-effort — falha silenciosa)."""
import os
import httpx

MULTICA_URL = os.getenv("MULTICA_API_URL", "http://localhost:3000")
MULTICA_TOKEN = os.getenv("MULTICA_PAT_TOKEN", "")
MULTICA_WS = os.getenv("MULTICA_WORKSPACE_ID", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {MULTICA_TOKEN}",
        "X-Workspace-ID": MULTICA_WS,
        "Content-Type": "application/json",
    }


async def create_project(title: str, description: str) -> str | None:
    """Cria project no Multica. Retorna multica_project_id ou None em falha."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{MULTICA_URL}/api/projects",
                headers=_headers(),
                json={"title": title, "description": description},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()["id"]
    except Exception as e:
        print(f"[multica] WARN create_project falhou: {e}", flush=True)
        return None


async def update_project(multica_id: str, title: str, description: str) -> None:
    """Atualiza project no Multica via PUT (PATCH retorna 405)."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{MULTICA_URL}/api/projects/{multica_id}",
                headers=_headers(),
                json={"title": title, "description": description},
                timeout=10,
            )
            resp.raise_for_status()
    except Exception as e:
        print(f"[multica] WARN update_project falhou: {e}", flush=True)


async def create_issue(agent_name: str, title: str, body: str, extra: dict | None = None) -> str | None:
    """Cria issue no Multica para acionar um agente. Retorna issue_id ou None em falha."""
    try:
        payload: dict = {"title": title, "body": body, "agent_name": agent_name}
        if extra:
            payload.update(extra)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{MULTICA_URL}/api/issues",
                headers=_headers(),
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("id")
    except Exception as e:
        print(f"[multica] WARN create_issue falhou: {e}", flush=True)
        return None


async def add_comment(issue_id: str, content: str) -> bool:
    """Adiciona comentário a uma issue do Multica. Retorna True em sucesso."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{MULTICA_URL}/api/issues/{issue_id}/comments",
                headers=_headers(),
                json={"content": content},
                timeout=10,
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        print(f"[multica] WARN add_comment falhou issue_id={issue_id}: {e}", flush=True)
        return False


async def close_issue(issue_id: str, title: str) -> bool:
    """Muda status da issue para 'done' via PUT. Retorna True em sucesso."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{MULTICA_URL}/api/issues/{issue_id}",
                headers=_headers(),
                json={"title": title, "status": "done"},
                timeout=10,
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        print(f"[multica] WARN close_issue falhou issue_id={issue_id}: {e}", flush=True)
        return False


async def delete_project(multica_id: str) -> None:
    """Deleta project no Multica. Best-effort: ignora 404."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{MULTICA_URL}/api/projects/{multica_id}",
                headers=_headers(),
                timeout=10,
            )
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
    except Exception as e:
        print(f"[multica] WARN delete_project falhou: {e}", flush=True)
