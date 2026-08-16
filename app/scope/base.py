from abc import ABC, abstractmethod
from pathlib import Path


class ScopeResolver(ABC):
    """Decides *which files* get analyzed for a run. The MVP only has
    FullAppScope (walk everything). GitDiffScope is the extension point for
    when a GitHub repo + branch/PR is supplied instead of a raw upload —
    see git_diff.py."""

    @abstractmethod
    def resolve(self, workspace_root: Path) -> list[tuple[Path, str]]:
        """Returns a list of (absolute_path, workspace_relative_path)."""
        raise NotImplementedError
