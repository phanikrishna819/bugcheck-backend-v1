from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app import db
from app.agent import service, sessions
from app.config import settings
from app.pipeline import analyze_workspace
from app.report.pdf import render_fixes_pdf
from app.workspace import resolver

router = APIRouter(prefix="/api/chat", tags=["chat"])


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace_root: str | None = Field(default=None, alias="workspaceRoot")
    allow_edits: bool = Field(default=False, alias="allowEdits")


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(min_length=1)
    workspace_root: str | None = Field(default=None, alias="workspaceRoot")
    allow_edits: bool | None = Field(default=None, alias="allowEdits")


@router.post("/sessions")
def create_session(request: SessionCreateRequest):
    workspace = None
    if request.workspace_root and request.workspace_root.strip():
        workspace = resolver.bind(request.workspace_root)
    return sessions.create(workspace, request.allow_edits)


@router.get("/sessions")
def list_sessions(limit: int = 50):
    return sessions.list_responses(limit)


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return sessions.to_response(session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    if db.get_session(session_id) is None:
        raise HTTPException(404, f"Chat session not found: {session_id}")
    db.delete_session(session_id)


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, request: MessageCreateRequest):
    try:
        sessions.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc

    if request.workspace_root is not None and request.workspace_root.strip():
        sessions.bind_workspace(session_id, request.workspace_root)
    if request.allow_edits is not None:
        db.update_session(session_id, allow_edits=request.allow_edits)

    service.respond(session_id, request.content)
    return sessions.to_response(session_id)


@router.post("/sessions/{session_id}/report.pdf")
def session_report_pdf(session_id: str):
    """Scan the session's registered workspace and return a fix PDF."""
    session = sessions.get(session_id)
    root = session.get("workspace_root")
    if not root or not Path(root).is_dir():
        raise ValueError("Register a workspace (git URL or local path) before generating a PDF report.")

    report = analyze_workspace(
        Path(root), uuid4().hex[:12], max_files_for_llm=settings.pdf_max_files_for_llm,
    )
    pdf = render_fixes_pdf(report)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="buggy-fixes-{session_id[:8]}.pdf"'},
    )
