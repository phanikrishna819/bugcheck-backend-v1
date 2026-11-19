"""
The agent tool loop (port of the Java OpenAiAgentService).

Differences that matter:
  * the full transcript is persisted, so follow-up turns keep the tool context
    the model already gathered (the Java version only kept the final text);
  * provider selection/fallback lives in app.agent.llm.ModelRouter;
  * a missing workspace does not create a broken tool session - the model is
    simply called without tools.
"""
from pathlib import Path

from app import db
from app.agent import sessions
from app.agent.llm import LLMError, router
from app.agent.prompts import build_system_prompt
from app.config import settings
from app.tools.common import ToolContext
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.registry import execute

MAX_ROUND_MESSAGE = (
    "I hit my tool-call limit for this turn before finishing. "
    "Ask me to continue and I'll pick up where I left off."
)


def _build_messages(history: list[dict], workspace: str | None, allow_edits: bool) -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(workspace, allow_edits)},
    ]
    window = history[-max(2, settings.agent_max_history_messages):]
    while window and window[0]["role"] == "tool":
        window = window[1:]

    for message in window:
        role = message["role"]
        if role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": message["tool_call_id"] or "",
                "name": message["tool_name"] or "tool",
                "content": message["content"],
            })
            continue
        entry = {"role": role, "content": message["content"] or ""}
        if role == "assistant" and message["tool_calls"]:
            entry["tool_calls"] = message["tool_calls"]
        messages.append(entry)
    return messages


def respond(session_id: str, user_message: str) -> str:
    session = sessions.get(session_id)
    workspace = session["workspace_root"]
    allow_edits = bool(session["allow_edits"])

    root: Path | None = None
    if workspace:
        candidate = Path(workspace)
        if candidate.is_dir():
            root = candidate
        else:
            workspace = None
            db.update_session(session_id, workspace_root=None)

    ctx = ToolContext(root=root, allow_edits=allow_edits)
    tools = TOOL_DEFINITIONS if root is not None else None

    db.add_message(session_id, "user", user_message)
    messages = _build_messages(db.list_messages(session_id), workspace, allow_edits)

    rounds = max(1, settings.agent_max_tool_rounds)
    for _ in range(rounds):
        turn = router.complete("chat", messages, tools=tools, temperature=settings.agent_temperature)
        content = (turn.content or "").strip()

        if not turn.tool_calls:
            text = content or "The agent returned an empty response."
            db.add_message(session_id, "assistant", text)
            return text

        db.add_message(
            session_id, "assistant", content,
            tool_calls=[{"id": call.id, "type": "function",
                         "function": {"name": call.name, "arguments": call.arguments}}
                        for call in turn.tool_calls],
            hidden=not content,
        )
        messages.append(turn.message)

        for call in turn.tool_calls:
            result = execute(call.name, call.arguments, ctx)
            status = "OK" if result.ok else "ERROR"
            db.add_message(
                session_id, "tool", f"{call.name}: {status}\n{result.output}",
                tool_name=call.name, tool_call_id=call.id,
            )
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.name,
                "content": result.output,
            })

    # Budget spent: ask for a final, tool-free summary instead of dropping a
    # bare "max rounds" notice on the user.
    nudge = (
        "Tool budget exhausted. Do not call any more tools. Using only what you "
        "have already learned, summarize the concrete bugs with file:line evidence "
        "and minimal fixes."
    )
    text = ""
    try:
        final = router.complete(
            "chat", [*messages, {"role": "user", "content": nudge}],
            tools=None, temperature=settings.agent_temperature,
        )
        text = (final.content or "").strip()
    except LLMError:
        text = ""
    text = text or MAX_ROUND_MESSAGE
    db.add_message(session_id, "assistant", text)
    return text


__all__ = ["respond", "LLMError"]
