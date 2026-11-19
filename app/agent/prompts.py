"""
System-prompt assembly: the bugcheck agent prompt plus every skill file, the
same contract the Java backend had, but reading from the bundled
`app/assets` by default so the deployment is self-contained.
"""
from pathlib import Path

from app.config import settings


def assets_root() -> Path:
    return settings.assets_path


def list_skill_names() -> list[str]:
    skills_dir = assets_root() / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.suffix == ".md")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return f"Missing or unreadable file: {path}"


def _skills_block() -> str:
    skills_dir = assets_root() / "skills"
    if not skills_dir.is_dir():
        return f"No skills directory found at {skills_dir}"
    blocks = []
    for name in list_skill_names():
        blocks.append(f"\n## {name}\n```markdown\n{_read(skills_dir / name)}\n```\n")
    return "".join(blocks)


def build_system_prompt(workspace_root: str | None, allow_edits: bool) -> str:
    agent_prompt = _read(assets_root() / "bugcheck.agent.md")
    return f"""You are Buggy, the Bugcheck Agent: an autonomous code-review and bug-fix agent exposed through a chat UI.

How to report (important):
- Do NOT list or paste the repository's files, directory trees, or whole file contents. Work silently with your tools.
- Only mention files that contain a concrete bug or problem, and always cite file:line evidence.
- Answer as a short numbered list of issues, each with its user impact and the minimal fix.
- Do not add a section describing which files you inspected or how many.
- If nothing is wrong, reply exactly: "No bugs found in this review." and stop.
- Tool budget: work efficiently. Locate candidates with list_files/grep_files, then read only the promising files; do not read files one by one.
- For any review request, inspect the code with tools first; never answer from assumptions or from this prompt alone.
- If the tool budget is nearly spent, stop and report the findings you already have.

Follow these hard safety rules:
- Use only the tools provided by the backend.
- Never edit files unless the session explicitly enables edits.
- Never edit outside the registered workspace root.
- Never run git reset, git clean, git checkout, git switch, git commit, git push, or destructive shell commands.
- Prefer minimal, targeted changes.
- Quote real files and line numbers when reporting findings.
- If a tool returns an ERROR, adapt; do not repeat the same failing call.

Session state:
- Workspace root: {workspace_root or "(none registered yet — ask the user for a git URL or local path)"}
- Edits allowed: {allow_edits}

Main bugcheck agent file:
```markdown
{agent_prompt}
```

Skill files:
{_skills_block()}
"""
