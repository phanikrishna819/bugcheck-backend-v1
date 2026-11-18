"""Chat-session persistence + the JSON shape the deployed React UI expects."""
import uuid

from app import db
from app.workspace import resolver

_UI_TOOL_CONTENT_LIMIT = 4000


def create(workspace: str | None, allow_edits: bool) -> dict:
    session_id = uuid.uuid4().hex
    db.create_session(session_id, workspace, allow_edits)
    return to_response(session_id)


def get(session_id: str) -> dict:
    session = db.get_session(session_id)
    if session is None:
        raise KeyError(f"Chat session not found: {session_id}")
    return session


def to_response(session_id: str) -> dict:
    session = get(session_id)
    messages = []
    for message in db.list_messages(session_id):
        if message["hidden"]:
            continue
        content = message["content"]
        if message["role"] == "tool" and len(content) > _UI_TOOL_CONTENT_LIMIT:
            content = content[:_UI_TOOL_CONTENT_LIMIT] + "\n... (truncated in UI)"
        messages.append({
            "role": message["role"],
            "content": content,
            "createdAt": message["created_at"],
        })
    return {
        "id": session["id"],
        "workspaceRoot": session["workspace_root"],
        "allowEdits": bool(session["allow_edits"]),
        "messages": messages,
    }


def list_responses(limit: int = 50) -> list[dict]:
    return [to_response(row["id"]) for row in db.list_sessions(limit)]


def bind_workspace(session_id: str, reference: str) -> str:
    path = resolver.bind(reference, session_id=session_id)
    db.update_session(session_id, workspace_root=path)
    return path
