"""Shared types and helpers for the agent's tool layer."""
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {
    ".git", "node_modules", "target", "dist", "build", ".venv", "venv", "__pycache__",
    ".idea", ".next", ".gradle", "coverage", ".pytest_cache", ".mypy_cache", ".turbo",
}


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str

    def as_tool_content(self, limit: int) -> str:
        text = self.output or ""
        if len(text) <= limit:
            return text
        head = text[: limit // 2]
        tail = text[-(limit // 2):]
        return f"{head}\n... [truncated {len(text) - limit} chars] ...\n{tail}"


@dataclass(frozen=True)
class ToolContext:
    root: Path
    allow_edits: bool


def ok(output: str) -> ToolResult:
    return ToolResult(True, output)


def error(output: str) -> ToolResult:
    return ToolResult(False, output)


def file_output(text: str) -> ToolResult:
    return ok(text if text.strip() else "(empty file)")
