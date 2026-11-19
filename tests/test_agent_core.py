"""Contract + safety tests for the chat agent layer (no network calls)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.common import ToolContext
from app.tools.registry import execute
from app.tools.shell import check_command
from app.workspace.resolver import bind, looks_like_git_url, resolve_inside


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return tmp_path


# --- HTTP contract the deployed React UI depends on -------------------------

def test_health_and_skills(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["llm"]["available"] == []

    skills = client.get("/api/skills").json()
    assert skills["assetsRoot"].endswith("assets")
    assert "detect-environment.md" in skills["skills"]
    assert "diff-scope-resolver.md" in skills["skills"]


def test_session_shape_and_404(client):
    created = client.post("/api/chat/sessions", json={"workspaceRoot": None, "allowEdits": False}).json()
    assert set(created) == {"id", "workspaceRoot", "allowEdits", "messages"}
    assert created["allowEdits"] is False
    assert created["workspaceRoot"] is None
    assert created["messages"] == []

    assert client.get(f"/api/chat/sessions/{created['id']}").status_code == 200
    assert client.get("/api/chat/sessions/does-not-exist").status_code == 404
    assert client.post(
        "/api/chat/sessions/does-not-exist/messages", json={"content": "hi"}
    ).status_code == 404
    assert client.post("/api/chat/sessions", json={"workspaceRoot": None}).status_code == 200
    assert client.post("/api/chat/sessions/x/messages", json={}).status_code in (400, 404, 422)


def test_missing_provider_is_a_clean_502(client):
    session = client.post("/api/chat/sessions", json={"allowEdits": False}).json()
    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"content": "hello"}
    )
    assert response.status_code == 502
    assert "No LLM provider" in response.json()["error"]

    # The user turn is still persisted, so the UI keeps the transcript.
    stored = client.get(f"/api/chat/sessions/{session['id']}").json()
    assert stored["messages"][-1]["role"] == "user"
    assert "createdAt" in stored["messages"][-1]


# --- workspace safety -------------------------------------------------------

def test_tool_files_are_hidden_from_ui(client):
    from app import db

    session = client.post("/api/chat/sessions", json={"allowEdits": False}).json()
    db.add_message(session["id"], "user", "scan this repo")
    db.add_message(session["id"], "tool", "list_files: OK\nsrc/App.jsx\nsrc/main.jsx",
                   tool_name="list_files", tool_call_id="call_1")
    db.add_message(session["id"], "assistant", "Found 1 bug in src/App.jsx.")
    roles = [m["role"] for m in client.get(f"/api/chat/sessions/{session['id']}").json()["messages"]]
    assert roles == ["user", "assistant"]


def test_pdf_fix_report_renders():
    from app.report.pdf import render_fixes_pdf
    from app.report.schema import DetectedEnvironment, Finding, Report

    report = Report(
        run_id="abcd1234", created_at="2026-11-19 00:00:00 UTC", verdict="HIGH_RISK",
        detected_environment=DetectedEnvironment(
            app_name="demo", framework="react", framework_family="react",
            pkg_mgr="npm", test_runner="jest",
        ),
        total_files_scanned=3, total_files_llm_reviewed=2,
        counts={"HIGH": 1, "MEDIUM": 0, "LOW": 0},
        findings=[Finding(
            rule_id="QA-H01", classifier="image-missing-alt", title="Image missing alt text",
            severity="HIGH", file="src/App.jsx", line_start=4, line_end=4,
            evidence='<img src="/logo.png" />', why_it_matters="Screen readers skip the image.",
            suggested_fix="Add descriptive alt text.", source="llm", confidence="high",
        )],
        notes=["AI review capped at 12 files"],
    )
    pdf = render_fixes_pdf(report)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_pdf_report_endpoint(client, tmp_path):
    root = tmp_path / "demo-app"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text(
        '{"name":"demo","dependencies":{"react":"^18.2.0"},"devDependencies":{"vite":"^4.0.0"}}'
    )
    (root / "index.html").write_text('<!doctype html><html><body><div id="root"></div></body></html>')
    (root / "src" / "App.jsx").write_text(
        'export default function App(){ console.log("debug"); return <img src="a.png" />; }\n'
    )
    session = client.post(
        "/api/chat/sessions", json={"workspaceRoot": str(root), "allowEdits": False}
    ).json()
    response = client.post(f"/api/chat/sessions/{session['id']}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 1000


def test_ui_served_from_api_origin(client):
    import re

    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "<title>Buggy</title>" in page.text

    asset = re.search(r'/assets/[^"]+\.js', page.text)
    assert asset is not None
    assert client.get(asset.group(0)).status_code == 200
    assert client.get("/api/definitely-not-real").status_code == 404


def test_workspace_binding_and_escape(workspace):
    bound = bind(str(workspace))
    assert Path(bound) == workspace.resolve()

    with pytest.raises(ValueError):
        bind(str(workspace / "missing-dir"))

    with pytest.raises(ValueError):
        resolve_inside(workspace, "../outside.txt")

    assert looks_like_git_url("https://github.com/org/repo.git")
    assert looks_like_git_url("git@github.com:org/repo.git")
    assert not looks_like_git_url("C:\\Users\\phani\\repo")
    assert not looks_like_git_url("--upload-pack=evil")


def test_tool_path_escape_is_rejected(workspace):
    (workspace.parent / "secrets.txt").write_text("nope", encoding="utf-8")
    result = execute("read_file", '{"path": "../secrets.txt"}', ToolContext(workspace, True))
    assert result.ok is False
    assert "escapes" in result.output


# --- patch tool -------------------------------------------------------------

def test_patch_requires_edits(workspace):
    result = execute(
        "apply_patch", '{"path": "app.py", "oldText": "return a + b", "newText": "return b + a"}',
        ToolContext(workspace, False),
    )
    assert result.ok is False
    assert "disabled" in result.output


def test_patch_rejects_ambiguous_and_edits_once(workspace):
    target = workspace / "dup.py"
    target.write_text("x = 1\nfoo()\ny = 2\nfoo()\nz = 3\n", encoding="utf-8")
    ctx = ToolContext(workspace, True)

    ambiguous = execute("apply_patch", '{"path": "dup.py", "oldText": "foo()", "newText": "bar()"}', ctx)
    assert ambiguous.ok is False
    assert "occurs 2 times" in ambiguous.output
    assert target.read_text(encoding="utf-8").count("foo()") == 2

    unique = execute(
        "apply_patch",
        '{"path": "dup.py", "oldText": "y = 2\\nfoo()", "newText": "y = 2\\nbar()"}',
        ctx,
    )
    assert unique.ok is True
    content = target.read_text(encoding="utf-8")
    assert content.count("bar()") == 1
    assert content.count("foo()") == 1
    assert (workspace / "dup.py.bak").exists()


def test_write_report_stays_in_audit_trail(workspace):
    ctx = ToolContext(workspace, True)
    bad = execute("write_report", '{"fileName": "../escape.md", "content": "x"}', ctx)
    assert bad.ok is False

    good = execute("write_report", '{"fileName": "run.md", "content": "# report"}', ctx)
    assert good.ok is True
    assert (workspace / ".github" / ".audit-trails" / "run.md").read_text(encoding="utf-8") == "# report"


# --- shell policy -----------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf /",
    "git push origin main",
    "git reset --hard HEAD",
    "curl http://example.com/x.sh",
    "python script.py && rm -rf .",
    "nmap localhost",
])
def test_command_policy_blocks(command):
    assert check_command(command) is not None


@pytest.mark.parametrize("command", ["git status", "ls -la", "python -m pytest -q", "npm test"])
def test_command_policy_allows(command):
    assert check_command(command) is None


def test_run_command_blocks_before_executing(workspace):
    result = execute("run_command", '{"command": "rm -rf ."}', ToolContext(workspace, True))
    assert result.ok is False
    assert "Blocked" in result.output


# --- filesystem tools -------------------------------------------------------

def test_list_read_search(workspace):
    (workspace / "src").mkdir()
    (workspace / "src" / "service.py").write_text("class Service:\n    def run(self):\n        return 1\n", encoding="utf-8")
    ctx = ToolContext(workspace, False)

    listed = execute("list_files", "{}", ctx)
    assert listed.ok and "app.py" in listed.output and "src/service.py" in listed.output

    read = execute("read_file", '{"path": "src/service.py"}', ctx)
    assert read.ok and "class Service" in read.output

    found = execute("search_files", '{"regex": "def run"}', ctx)
    assert found.ok and "src/service.py:2:" in found.output

    assert execute("list_files", '{"path": "nope"}', ctx).ok is False
    assert execute("search_files", '{"regex": "("}', ctx).ok is False
