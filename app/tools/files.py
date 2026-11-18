"""Read-only filesystem tools, confined to the session workspace."""
import os
import re
from pathlib import Path

from app.config import settings
from app.tools.common import IGNORED_DIRS, ToolContext, ToolResult, error, file_output, ok
from app.workspace.resolver import relativize, resolve_inside


def list_files(ctx: ToolContext, path: str = "", limit: int = 200) -> ToolResult:
    limit = max(1, min(int(limit or 200), 1000))
    start = resolve_inside(ctx.root, path or "")
    if not start.exists():
        return error(f"Path does not exist: {path or '.'}")
    if start.is_file():
        return ok(relativize(ctx.root, start))

    max_depth = settings.agent_max_walk_depth
    base_depth = len(start.parts)
    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(start):
        depth = len(Path(dirpath).parts) - base_depth
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in dirnames:
            entries.append(relativize(ctx.root, Path(dirpath) / name) + "/")
        for name in sorted(filenames):
            entries.append(relativize(ctx.root, Path(dirpath) / name))
        if len(entries) >= limit:
            break
    return ok("\n".join(entries[:limit]) if entries else "(no files)")


def read_file(ctx: ToolContext, path: str) -> ToolResult:
    target = resolve_inside(ctx.root, path)
    if not target.is_file():
        return error(f"File not found: {path}")
    size = target.stat().st_size
    if size > settings.agent_max_file_bytes:
        return error(f"File is too large for this tool ({size} bytes > {settings.agent_max_file_bytes}).")
    return file_output(target.read_text(encoding="utf-8", errors="replace"))


def search_files(ctx: ToolContext, regex: str, limit: int = 100) -> ToolResult:
    limit = max(1, min(int(limit or 100), 500))
    try:
        pattern = re.compile(regex)
    except re.error as exc:
        return error(f"Invalid regex: {exc}")

    max_depth = settings.agent_max_walk_depth + 4
    base_depth = len(ctx.root.parts)
    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        depth = len(Path(dirpath).parts) - base_depth
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            file_path = Path(dirpath) / name
            try:
                if file_path.stat().st_size > settings.agent_max_file_bytes:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "\x00" in text[:2048]:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{relativize(ctx.root, file_path)}:{number}: {line[:400]}")
                    if len(matches) >= limit:
                        return ok("\n".join(matches))
    return ok("\n".join(matches) if matches else "(no matches)")
