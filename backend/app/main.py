"""FastAPI application entry point for the Legal Metrology Inspection Platform."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import (
    admin,
    analysis,
    auth,
    dashboard,
    evidence,
    images,
    inspections,
    meta,
    pipeline,
    reports,
    review,
)

API_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Legal Metrology Inspection Platform",
    description=(
        "AI-assisted package inspection: image quality -> OCR -> field matching -> "
        "deterministic version-aware rule engine -> evidence-backed compliance report. "
        "The LLM only maps text to fields; every pass/fail decision is deterministic."
    ),
    version=API_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth")
app.include_router(inspections.router, prefix="/api")
app.include_router(images.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Legal Metrology Inspection Platform",
        "version": API_VERSION,
        "ocr_engine": settings.OCR_ENGINE,
        "field_matcher": settings.FIELD_MATCHER,
    }


@app.get("/")
def root():
    return {
        "name": "Legal Metrology Inspection Platform API",
        "version": API_VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }
