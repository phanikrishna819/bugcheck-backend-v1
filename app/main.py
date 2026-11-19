"""
Bugcheck backend (FastAPI).

Two feature sets share one process:

  * /api/chat/*  - the chat/tool agent (OpenAI-compatible providers, workspace
                   tools, SQLite-backed sessions) consumed by the existing
                   React UI in bugcheck-agent-chatbot/frontend.
  * /api/analyze - the original zip-upload static + AI scan pipeline.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.agent.llm import LLMError
from app.api import chat, health, scan, skills, workspaces
from app.config import settings

logger = logging.getLogger("bugcheck")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    settings.upload_tmp_path
    settings.reports_path
    settings.workspace_path
    purged = db.purge_expired_sessions(settings.session_ttl_minutes)
    if purged:
        logger.info("Purged %s expired chat session(s).", purged)
    yield


app = FastAPI(
    title="Buggy API",
    description="Buggy (the Bugcheck Agent): chat-based code review with workspace tools, "
                "on-demand PDF fix reports, plus the upload-and-scan frontend analyzer.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.exception_handler(ValueError)
def handle_value_error(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(KeyError)
def handle_key_error(_request: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"error": str(exc).strip("'")})


@app.exception_handler(LLMError)
def handle_llm_error(_request: Request, exc: LLMError):
    logger.warning("LLM failure: %s", exc)
    text = str(exc)
    if "429" in text or "quota" in text.lower():
        return JSONResponse(
            status_code=429,
            content={"error": "The AI provider's free-tier quota is exhausted. "
                              "Wait for it to reset or configure another provider key."},
        )
    return JSONResponse(status_code=502, content={"error": text})


@app.exception_handler(RequestValidationError)
def handle_validation_error(_request: Request, _exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": "Request validation failed."})


@app.exception_handler(Exception)
def handle_unexpected(_request: Request, exc: Exception):
    logger.exception("Unhandled API error", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error."})


app.include_router(health.router)
app.include_router(skills.router)
app.include_router(workspaces.router)
app.include_router(chat.router)
app.include_router(scan.router)

if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_ui(full_path: str):
    """Serve the bundled React UI from the API origin (single-service deploy)."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    if full_path:
        candidate = (STATIC_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
            return FileResponse(candidate)

    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)

    return JSONResponse({
        "service": "bugcheck-agent-api",
        "docs": "/docs",
        "health": "/api/health",
        "chat": "/api/chat/sessions",
        "scan": "/api/analyze",
    })
