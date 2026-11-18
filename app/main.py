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

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.agent.llm import LLMError
from app.api import chat, health, scan, skills, workspaces
from app.config import settings

logger = logging.getLogger("bugcheck")


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
    return JSONResponse(status_code=502, content={"error": str(exc)})


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


@app.get("/")
def index():
    return {
        "service": "bugcheck-agent-api",
        "docs": "/docs",
        "health": "/api/health",
        "chat": "/api/chat/sessions",
        "scan": "/api/analyze",
    }
