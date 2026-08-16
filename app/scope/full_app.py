from pathlib import Path

from app.scope.base import ScopeResolver
from app.utils.file_walk import walk_scannable_files


class FullAppScope(ScopeResolver):
    """Scans every scannable file in the upload. This is the right default
    for a beginner "upload my whole app" flow, and the wrong default at
    scale: see README "Why there's a file cap" for why LLM review gets
    prioritized/capped downstream in pipeline.py, and GitDiffScope below
    for the real fix once branch-based analysis is available."""

    def resolve(self, workspace_root: Path) -> list[tuple[Path, str]]:
        return list(walk_scannable_files(workspace_root))
