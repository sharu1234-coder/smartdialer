from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.database import create_all_tables
from app.providers.provider_factory import initialize_default_providers
from app.api import health, campaigns, agents, borrowers, dialer, calls, providers, simulation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SmartDialer...")
    create_all_tables()
    initialize_default_providers()
    logger.info("SmartDialer started.")
    yield
    logger.info("SmartDialer shutting down.")


app = FastAPI(
    title="SmartDialer",
    version="1.0.0",
    description=(
        "Production-grade SmartDialer with Progressive and Predictive modes, "
        "Safety Controller, and two mock telecom providers."
    ),
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(campaigns.router, prefix="/api/campaigns", tags=["campaigns"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(borrowers.router, prefix="/api/borrowers", tags=["borrowers"])
app.include_router(dialer.router, prefix="/api/dialer", tags=["dialer"])
app.include_router(calls.router, prefix="/api/calls", tags=["calls"])
app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
app.include_router(simulation.router, prefix="/api/simulation", tags=["simulation"])


@app.get("/")
def root():
    return {
        "name": "SmartDialer",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health/live",
    }
