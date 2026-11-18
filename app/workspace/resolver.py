"""
Workspace binding + path containment.

A workspace arrives either as a local directory path (the Java backend's only
mode) or as a git URL, which is shallow-cloned into `WORKSPACE_DIR` so the
agent can actually analyze code when the backend runs in a container where no
user repositories exist.

Everything the tools do is then confined with `resolve_inside`, which rejects
any path that normalizes outside the workspace root.
"""
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from app import db
from app.config import settings

_GIT_URL_RE = re.compile(r"^(https?://|ssh://|git://|git@)", re.IGNORECASE)


def looks_like_git_url(value: str) -> bool:
    value = (value or "").strip()
    if not value or value.startswith("-"):
        return False
    return bool(_GIT_URL_RE.match(value))


def _slug(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _dir_size_mb(root: Path, stop_after_mb: int) -> float:
    total = 0
    seen = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
            seen += 1
            if seen % 500 == 0 and total > stop_after_mb * 1024 * 1024:
                return total / (1024 * 1024)
    return total / (1024 * 1024)


def _clone(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (destination / ".git").is_dir():
        return destination
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", url, str(destination)],
            capture_output=True, text=True, timeout=settings.clone_timeout_seconds, env=env,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError(f"git clone timed out after {settings.clone_timeout_seconds}s: {url}")
    except OSError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError(f"git is not available or failed to start: {exc}")

    if result.returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = " | ".join(detail[-3:])[:400] or "unknown git error"
        raise ValueError(f"git clone failed: {tail}")

    size_mb = _dir_size_mb(destination, settings.clone_max_repo_mb)
    if size_mb > settings.clone_max_repo_mb:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError(
            f"Repository is too large ({size_mb:.0f} MB > {settings.clone_max_repo_mb} MB limit)."
        )
    return destination


def bind(value: str, session_id: str | None = None, register: bool = True) -> str:
    """Resolve a user-supplied workspace reference to a local absolute path."""
    value = (value or "").strip()
    if not value:
        raise ValueError("A workspace path or git URL is required.")

    mode = settings.workspace_mode.strip().lower()
    if looks_like_git_url(value):
        if mode == "local":
            raise ValueError("WORKSPACE_MODE=local, but a git URL was provided.")
        destination = settings.workspace_path / (session_id or _slug(value)) / "repo"
        root = _clone(value, destination)
    else:
        if mode == "clone":
            raise ValueError("WORKSPACE_MODE=clone, but a local path was provided.")
        root = Path(value).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Workspace must be an existing directory or a git URL: {value}")

    if register:
        db.register_workspace(str(root))
    return str(root)


def resolve_inside(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = Path(relative or "")
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes the workspace: {relative}")
    return resolved


def relativize(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def is_registered(path: str) -> bool:
    return db.is_registered_workspace(str(Path(path).expanduser().resolve()))
