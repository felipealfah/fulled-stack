"""
Autenticação da Stack — token HMAC assinado (stdlib pura, sem dependências novas).

Modos de acesso quando AUTH_ENABLED=true:
  1. Dashboard: POST /auth/login → token Bearer (validade 30 dias)
  2. Scripts/agentes: header `x-api-key` == STACK_API_KEY

Com AUTH_ENABLED=false (default), nada muda — desenvolvimento local segue sem login.

Variáveis de ambiente:
  AUTH_ENABLED       "true"/"false" (default: false)
  DASHBOARD_USER     usuário do login (ex: felipe@fulled.com.br)
  DASHBOARD_PASSWORD senha do login (NUNCA commitar — vive só no .env)
  AUTH_SECRET        segredo de assinatura dos tokens (string aleatória longa)
  STACK_API_KEY      chave para scripts (header x-api-key)
"""

import base64
import hashlib
import hmac
import os
import time

TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 dias


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def _secret() -> bytes:
    secret = os.environ.get("AUTH_SECRET", "")
    if not secret:
        # Fallback: deriva do password para não quebrar se AUTH_SECRET faltar.
        # Ainda assim, defina AUTH_SECRET explicitamente em produção.
        secret = "fulled-derived:" + os.environ.get("DASHBOARD_PASSWORD", "")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _sign(payload_b64: str) -> str:
    sig = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")


def create_token(username: str) -> tuple[str, int]:
    """Retorna (token, expires_at_epoch)."""
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{username}|{expires_at}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{payload_b64}.{_sign(payload_b64)}", expires_at


def verify_token(token: str) -> str | None:
    """Retorna o username se o token for válido e não expirado; senão None."""
    try:
        payload_b64, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload_b64)):
            return None
        padding = "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        username, expires_at = payload.rsplit("|", 1)
        if int(expires_at) < time.time():
            return None
        return username
    except Exception:
        return None


def check_credentials(username: str, password: str) -> bool:
    expected_user = os.environ.get("DASHBOARD_USER", "")
    expected_password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected_user or not expected_password:
        return False
    user_ok = hmac.compare_digest(username.strip().lower(), expected_user.strip().lower())
    pass_ok = hmac.compare_digest(password, expected_password)
    return user_ok and pass_ok


def check_api_key(key: str | None) -> bool:
    expected = os.environ.get("STACK_API_KEY", "")
    return bool(key) and bool(expected) and hmac.compare_digest(key, expected)


# ── Rate limiting simples do login (in-memory, por IP) ──
_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 8
WINDOW_SECONDS = 300  # 5 min


def login_rate_limited(ip: str) -> bool:
    now = time.time()
    history = [t for t in _attempts.get(ip, []) if now - t < WINDOW_SECONDS]
    _attempts[ip] = history
    return len(history) >= MAX_ATTEMPTS


def register_login_attempt(ip: str) -> None:
    _attempts.setdefault(ip, []).append(time.time())
