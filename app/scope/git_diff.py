"""
Not wired up yet. This is where skills/diff-scope-resolver.md's logic
belongs once the backend can clone/checkout a GitHub repo instead of only
accepting a zip upload — it's the actual fix for the "whole app is too
big for free-tier LLM rate limits" problem (see README), because most CI
runs and PR reviews only care about *changed* files.

Porting notes for whoever wires this in:
  - branchRef parsing (ADO `?version=GB<branch>` / GitHub `/tree/<branch>`
    / plain branch name) carries over unchanged — it's just URL parsing.
  - `git fetch` / `git merge-base` / `git diff --name-only` need a real
    clone on disk, so this resolver's __init__ should take a filesystem
    path to a repo the caller already cloned (e.g. via GitPython or a
    shallow `git clone --depth`), not the repo URL itself — keep the
    "how do we get the bytes onto disk" concern in the upload/ingestion
    layer, same separation FullAppScope has from the zip-extraction code
    in app/uploads/handler.py.
  - IGNORE_GLOBS filtering is already shared via app.utils.file_walk.
  - includesWorkingTree (uncommitted changes) matters for "analyze my
    current branch before I open a PR" — worth keeping if that flow is
    ever added; skip it for a pure "analyze this PR" flow.
"""
from pathlib import Path

from app.scope.base import ScopeResolver


class GitDiffScope(ScopeResolver):
    def __init__(self, repo_path: Path, base_ref: str, head_ref: str):
        self.repo_path = repo_path
        self.base_ref = base_ref
        self.head_ref = head_ref

    def resolve(self, workspace_root: Path) -> list[tuple[Path, str]]:
        raise NotImplementedError(
            "GitDiffScope is a placeholder for the future GitHub-repo-link flow. "
            "Port skills/diff-scope-resolver.md's steps 1-5 here, using GitPython "
            "or subprocess git calls against self.repo_path."
        )
