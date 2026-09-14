"""FastAPI application: CORS, routers, /health."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agent, approvals, evals, pos, scenarios, traces
from app.config import get_settings
from app.db.engine import Base, engine
from app.db import models as _models  # noqa: F401 — register metadata

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI Purchasing Agent",
    version="0.1.0",
    description=(
        "LLM-orchestrated purchasing agent. The model reasons; deterministic "
        "Python owns arithmetic, constraints, and post-verification."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scenarios.router)
app.include_router(agent.router)
app.include_router(pos.router)
app.include_router(approvals.router)
app.include_router(traces.router)
app.include_router(evals.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "purchasing-agent"}
