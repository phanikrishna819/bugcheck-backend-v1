"""Read-only git tools (status/diff). Git-writing commands are never exposed."""
import re

from app.tools.common import ToolContext, ToolResult, error
from app.tools.shell import run_process

_SAFE_REF = re.compile(r"^[A-Za-z0-9_./~^@{}-]+$")


def git_status(ctx: ToolContext) -> ToolResult:
    return run_process(["git", "status", "--short"], ctx.root, timeout=30)


def git_diff(ctx: ToolContext, base_ref: str = "") -> ToolResult:
    base_ref = (base_ref or "").strip()
    if base_ref:
        if base_ref.startswith("-") or not _SAFE_REF.match(base_ref):
            return error(f"Unsafe git ref: {base_ref}")
        argv = ["git", "diff", base_ref, "--", "."]
    else:
        argv = ["git", "diff", "--", "."]
    return run_process(argv, ctx.root, timeout=60)
