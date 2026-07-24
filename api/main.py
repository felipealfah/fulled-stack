from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
# v1.1.0
from dotenv import load_dotenv

load_dotenv()

import auth as auth_lib
from db import get_pool, close_pool
from routers import review, projects, projetos
from routers.auth import router as auth_router
from routers.agent_executions import router as agent_executions_router
from routers.ranking import router as ranking_router
from routers.overrides import router as overrides_router
from routers.seo_plan import router as seo_plan_router
from routers.geo_targets import router as geo_targets_router
from routers.content import router as content_router
from routers.prospeccao import router as prospeccao_router
from routers.financeiro import router as financeiro_router
from routers.keywords import router as keywords_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="FullED API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas públicas mesmo com AUTH_ENABLED=true
AUTH_EXEMPT_PATHS = {"/health", "/auth/login", "/auth/status"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protege toda a API quando AUTH_ENABLED=true.

    Acesso permitido via:
    - Bearer token (dashboard, obtido em /auth/login)
    - header x-api-key == STACK_API_KEY (scripts/agentes)
    Local (AUTH_ENABLED=false, default): passa direto — nada muda no dev.
    """
    if not auth_lib.auth_enabled():
        return await call_next(request)
    if request.method == "OPTIONS" or request.url.path in AUTH_EXEMPT_PATHS:
        return await call_next(request)
    if auth_lib.check_api_key(request.headers.get("x-api-key")):
        return await call_next(request)
    authz = request.headers.get("authorization", "")
    if authz.startswith("Bearer ") and auth_lib.verify_token(authz[7:]):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "Não autenticado"})


app.include_router(auth_router)
app.include_router(review.router)
app.include_router(projects.router)
app.include_router(projetos.router)
app.include_router(agent_executions_router)
app.include_router(ranking_router)
app.include_router(overrides_router)
app.include_router(seo_plan_router)
app.include_router(geo_targets_router)
app.include_router(content_router)
app.include_router(prospeccao_router)
app.include_router(financeiro_router)
app.include_router(keywords_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
