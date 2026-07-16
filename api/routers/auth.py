from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import auth as auth_lib

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/status")
async def auth_status():
    """Público — o frontend consulta para saber se exige login."""
    return {"auth_enabled": auth_lib.auth_enabled()}


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    if not auth_lib.auth_enabled():
        raise HTTPException(400, "Autenticação desativada neste ambiente")

    ip = request.client.host if request.client else "unknown"
    if auth_lib.login_rate_limited(ip):
        raise HTTPException(429, "Muitas tentativas — aguarde 5 minutos")

    if not auth_lib.check_credentials(body.username, body.password):
        auth_lib.register_login_attempt(ip)
        raise HTTPException(401, "Usuário ou senha inválidos")

    token, expires_at = auth_lib.create_token(body.username)
    return {"token": token, "user": body.username, "expires_at": expires_at}


@router.get("/me")
async def me(request: Request):
    """Valida o token atual (o middleware já barrou não-autenticados quando AUTH_ENABLED)."""
    if not auth_lib.auth_enabled():
        return {"user": None, "auth_enabled": False}
    authz = request.headers.get("authorization", "")
    user = auth_lib.verify_token(authz[7:]) if authz.startswith("Bearer ") else None
    if not user:
        raise HTTPException(401, "Não autenticado")
    return {"user": user, "auth_enabled": True}
