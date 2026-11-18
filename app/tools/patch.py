"""
Write-capable tools. Both require `allowEdits` and forbid touching `.git`.

`apply_patch` refuses ambiguous matches instead of replacing every occurrence
(the Java backend used String.replace, which silently rewrote all matches)
and keeps a `.bak` copy of the pre-edit file.
"""
import re
from pathlib import Path

from app.tools.common import ToolContext, ToolResult, error, ok
from app.workspace.resolver import relativize, resolve_inside

_REPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.md$")


def _in_git_dir(root: Path, target: Path) -> bool:
    try:
        return ".git" in target.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True


def apply_patch(ctx: ToolContext, path: str, old_text: str, new_text: str,
                create_if_missing: bool = False) -> ToolResult:
    if not ctx.allow_edits:
        return error("Edits are disabled for this session. Enable allowEdits first.")
    target = resolve_inside(ctx.root, path)
    if _in_git_dir(ctx.root, target):
        return error("Refusing to edit inside .git.")

    if not target.exists():
        if not create_if_missing:
            return error(f"File does not exist: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_text, encoding="utf-8")
        return ok(f"Created {relativize(ctx.root, target)}")

    if not target.is_file():
        return error(f"Not a regular file: {path}")

    content = target.read_text(encoding="utf-8", errors="replace")
    if not old_text:
        return error("oldText must not be empty when the file already exists.")

    occurrences = content.count(old_text)
    if occurrences == 0:
        return error("oldText was not found in the file.")
    if occurrences > 1:
        return error(
            f"oldText occurs {occurrences} times; add more surrounding context so the patch is unambiguous."
        )

    target.with_name(target.name + ".bak").write_text(content, encoding="utf-8")
    target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    return ok(f"Updated {relativize(ctx.root, target)} (backup: {target.name}.bak)")


def write_report(ctx: ToolContext, file_name: str, content: str) -> ToolResult:
    if not ctx.allow_edits:
        return error("Edits are disabled for this session. Enable allowEdits first.")
    name = (file_name or "").strip()
    if not _REPORT_NAME.match(name):
        return error("Report fileName must be a simple .md file name.")

    report_dir = resolve_inside(ctx.root, ".github/.audit-trails")
    report_dir.mkdir(parents=True, exist_ok=True)
    target = resolve_inside(ctx.root, f".github/.audit-trails/{name}")
    target.write_text(content or "", encoding="utf-8")
    return ok(f"Report written: {relativize(ctx.root, target)}")
