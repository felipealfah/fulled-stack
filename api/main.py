from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# v1.1.0
from dotenv import load_dotenv

load_dotenv()

from db import get_pool, close_pool
from routers import review, projects, projetos
from routers.agent_executions import router as agent_executions_router
from routers.ranking import router as ranking_router
from routers.overrides import router as overrides_router
from routers.seo_plan import router as seo_plan_router
from routers.geo_targets import router as geo_targets_router
from routers.content import router as content_router


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

app.include_router(review.router)
app.include_router(projects.router)
app.include_router(projetos.router)
app.include_router(agent_executions_router)
app.include_router(ranking_router)
app.include_router(overrides_router)
app.include_router(seo_plan_router)
app.include_router(geo_targets_router)
app.include_router(content_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
