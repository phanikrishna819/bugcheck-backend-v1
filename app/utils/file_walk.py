"""
Ported near-verbatim from skills/detect-environment.md steps 5 and 12.
That skill assumed a live git checkout; we operate on an extracted upload
instead, so step 12's fixed ignore list is unchanged but there's no git
step to combine it with.
"""
import fnmatch
from pathlib import Path

LANG_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"]
HTML_EXTS = [".html", ".htm"]
CSS_EXTS = [".css", ".scss", ".sass", ".less"]
SCANNABLE_EXTS = set(LANG_EXTS + HTML_EXTS + CSS_EXTS)

# Verbatim from detect-environment.md step 12, minus the git-specific
# ".gitignore" and "*.lock" entries (those are patterns to *read*, not skip)
IGNORE_GLOBS = [
    "dist/**",
    "build/**",
    ".next/**",
    "out/**",
    "storybook-static/**",
    "coverage/**",
    "node_modules/**",
    "**/__generated__/**",
    "**/*.min.*",
    "*.snap",
    ".git/**",
    "**/.git/**",
]


def is_ignored(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(norm, pattern) for pattern in IGNORE_GLOBS)


def walk_scannable_files(root: Path):
    """Yield (absolute_path, workspace_relative_path) for every file under
    root whose extension we know how to scan and that isn't ignored."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if is_ignored(rel):
            continue
        if path.suffix.lower() not in SCANNABLE_EXTS:
            continue
        yield path, rel
