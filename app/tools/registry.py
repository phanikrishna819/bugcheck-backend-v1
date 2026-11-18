"""Tool dispatch: name + JSON arguments -> ToolResult."""
import json
from typing import Callable

from app.config import settings
from app.tools import files, git, patch, shell
from app.tools.common import ToolContext, ToolResult, error
from app.tools.definitions import TOOL_DEFINITIONS


def _text(args: dict, key: str, default: str | None = None) -> str:
    value = args.get(key, default)
    if value is None:
        raise ValueError(f"Missing required argument: {key}")
    if not isinstance(value, str):
        value = str(value)
    if default is None and not value.strip():
        raise ValueError(f"Missing required argument: {key}")
    return value


def _int(args: dict, key: str, default: int) -> int:
    try:
        return int(args.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _bool(args: dict, key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


_HANDLERS: dict[str, Callable[[ToolContext, dict], ToolResult]] = {
    "list_files": lambda ctx, a: files.list_files(ctx, _text(a, "path", ""), _int(a, "limit", 200)),
    "read_file": lambda ctx, a: files.read_file(ctx, _text(a, "path")),
    "search_files": lambda ctx, a: files.search_files(ctx, _text(a, "regex"), _int(a, "limit", 100)),
    "git_status": lambda ctx, a: git.git_status(ctx),
    "git_diff": lambda ctx, a: git.git_diff(ctx, _text(a, "baseRef", "")),
    "run_command": lambda ctx, a: shell.run_shell(ctx, _text(a, "command")),
    "apply_patch": lambda ctx, a: patch.apply_patch(
        ctx, _text(a, "path"), _text(a, "oldText", ""), str(a.get("newText", "")),
        _bool(a, "createIfMissing"),
    ),
    "write_report": lambda ctx, a: patch.write_report(
        ctx, _text(a, "fileName"), str(a.get("content", "")),
    ),
}


def execute(name: str, arguments_json: str, ctx: ToolContext) -> ToolResult:
    handler = _HANDLERS.get(name)
    if handler is None:
        return error(f"Unknown tool: {name}")
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            return error("Tool arguments must be a JSON object.")
    except json.JSONDecodeError as exc:
        return error(f"Invalid JSON arguments: {exc}")

    try:
        result = handler(ctx, args)
    except ValueError as exc:
        result = error(str(exc))
    except Exception as exc:  # noqa: BLE001 - the model must always get a result back
        result = error(f"{type(exc).__name__}: {exc}")
    return ToolResult(result.ok, result.as_tool_content(settings.agent_max_output_chars))
