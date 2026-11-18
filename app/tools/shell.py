"""
Process execution helpers.

The Java backend read a child's output only after it exited, which deadlocks
any command producing more than the OS pipe buffer (~64 KB) and turns every
big `git diff` into a 60-second timeout. Here stdout is drained by a reader
thread while the process runs, and the timeout is enforced with `wait`.
"""
import re
import subprocess
import threading
from pathlib import Path

from app.config import settings
from app.tools.common import ToolResult, error, ok

_DENY_PATTERNS = [
    r"\bgit\s+(reset|clean|push|checkout|switch|commit|merge|rebase|tag|stash)\b",
    r"\b(rm|rmdir|del|erase|format|shutdown|reboot|sudo|chmod|chown|mkfs|dd)\b",
    r"\bremove-item\b",
    r"--force\b",
    r"--hard\b",
    r"\bcurl\b|\bwget\b|\biwr\b|\bstart-process\b|\binvoke-expression\b|\biex\b",
]
_SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\n|\|")


def _first_tokens(command: str) -> list[str]:
    tokens = []
    for segment in _SEGMENT_SPLIT.split(command):
        segment = segment.strip()
        if not segment:
            continue
        head = segment.split()[0]
        tokens.append(Path(head).name.lower())
    return tokens


def check_command(command: str) -> str | None:
    """Return a block reason, or None when the command is allowed."""
    if not settings.agent_allow_shell:
        return "Shell execution is disabled (AGENT_ALLOW_SHELL=false)."
    lowered = command.lower()
    for pattern in _DENY_PATTERNS:
        if re.search(pattern, lowered):
            return f"Blocked by policy (matched {pattern}): {command}"
    if not _first_tokens(command):
        return "Empty command."
    allowed = settings.allowed_commands
    for token in _first_tokens(command):
        token = token[:-4] if token.endswith(".exe") else token
        if token not in allowed:
            return f"Command '{token}' is not on the allowlist."
    return None


def _shell(command: str) -> list[str]:
    if Path("/bin/sh").exists():
        return ["/bin/sh", "-lc", command]
    return ["powershell", "-NoProfile", "-Command", command]


def run_process(argv: list[str], cwd: Path, timeout: int | None = None) -> ToolResult:
    timeout = timeout or settings.agent_command_timeout_seconds
    try:
        process = subprocess.Popen(
            argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as exc:
        return error(f"Failed to start process: {exc}")

    chunks: list[str] = []

    def _drain():
        assert process.stdout is not None
        for line in process.stdout:
            chunks.append(line)

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        reader.join(timeout=5)
        return error(f"Command timed out after {timeout}s: {' '.join(argv)}")
    reader.join(timeout=10)

    output = "".join(chunks).strip()
    return ok(output) if process.returncode == 0 else error(output or f"Exited with code {process.returncode}")


def run_shell(ctx, command: str) -> ToolResult:
    reason = check_command(command)
    if reason:
        return error(reason)
    return run_process(_shell(command), ctx.root)
