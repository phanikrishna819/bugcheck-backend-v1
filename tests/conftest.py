"""Test bootstrap: isolate DB/paths and force the no-provider code path."""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="bugcheck-tests-"))

os.environ["DATABASE_PATH"] = str(_TMP / "test.db")
os.environ["WORKSPACE_DIR"] = str(_TMP / "workspaces")
os.environ["UPLOAD_TMP_DIR"] = str(_TMP / "uploads")
os.environ["REPORTS_DIR"] = str(_TMP / "reports")
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["AGENT_ALLOW_SHELL"] = "true"
