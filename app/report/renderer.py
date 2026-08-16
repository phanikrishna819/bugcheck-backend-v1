"""
Ported from skills/report-renderer.md: the section structure (Verdict,
Detected Environment, Findings table, Findings Detail) and the
"forbidden sections" rule (no Files Changed / Classifier Signals /
Verification headers — that data already lives inside each finding) both
carry over as-is.

Dropped: step 5 ("Serve" — hash a port, `python3 -m http.server`, poll it)
and step 6 ("Open" — Simple Browser). Those exist because the original
skill runs *inside* an IDE agent that has a "open this URL" tool. A
FastAPI backend doesn't need that trick — it just writes the files and
returns their paths / serves them from its own static route
(see app/main.py's /api/reports/{run_id}/... endpoints). Markdown -> HTML
here is a tiny hand-rolled wrapper via the `markdown` package instead of
shelling out to a Node render script, since we can't assume Node exists
in this Python service's runtime.
"""
import html as html_escape
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib

from app.report.schema import Report
from app.config import settings

SEVERITY_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
COVERAGE_LABEL = {"static": "✅ deterministic check", "llm": "🤖 AI-reviewed"}


def _findings_table(report: Report) -> str:
    rows = ["| Rule ID | Severity | File:Line | Classifier | Detected via |", "|---|---|---|---|---|"]
    for f in report.findings:
        rows.append(
            f"| {f.rule_id} | {f.severity} | {f.file}:{f.line_start} | {f.classifier} | "
            f"{COVERAGE_LABEL.get(f.source, f.source)} |"
        )
    return "\n".join(rows)


def _findings_detail(report: Report) -> str:
    blocks = []
    for f in report.findings:
        icon = SEVERITY_ICON.get(f.severity, "")
        confidence_note = f" _(heuristic, confidence: {f.confidence})_" if f.confidence == "low" else ""
        blocks.append(
            f"### {icon} {f.severity} — {f.rule_id} — {f.title}{confidence_note}\n\n"
            f"**Where:** `{f.file}:{f.line_start}`" + (f"-{f.line_end}" if f.line_end and f.line_end != f.line_start else "") + "\n\n"
            f"**Evidence:**\n```\n{f.evidence}\n```\n\n"
            f"**Why it is a bug:** {f.why_it_matters}\n\n"
            f"**Suggested fix:**\n```\n{f.suggested_fix}\n```\n"
        )
    return "\n".join(blocks) if blocks else "_No findings._"


def render_markdown(report: Report) -> str:
    env = report.detected_environment
    env_table = (
        "| App name | Framework | Package manager |\n"
        "|---|---|---|\n"
        f"| {env.app_name or '(unnamed)'} | {env.framework} | {env.pkg_mgr} |"
    )
    parts = [
        f"# Bug Risk Report — {report.created_at}",
        f"**Verdict:** {report.verdict} {report.verdict_suffix}",
        "## Detected Environment",
        env_table,
        f"**Files scanned:** {report.total_files_scanned}  ·  **Files AI-reviewed:** {report.total_files_llm_reviewed}",
    ]
    if report.notes:
        parts.append("**Notes:** " + "; ".join(report.notes))
    parts += [
        "## Findings",
        _findings_table(report) if report.findings else "_No findings._",
        "## Findings Detail",
        _findings_detail(report),
    ]
    return "\n\n".join(parts)


def render_html(markdown_text: str, title: str) -> str:
    body = md_lib.markdown(markdown_text, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html_escape.escape(title)}</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; color: #1a1a1a; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9rem; }}
th {{ background: #f5f5f5; }}
code, pre {{ background: #f5f5f5; border-radius: 4px; }}
pre {{ padding: 10px; overflow-x: auto; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: .3rem; }}
h3 {{ margin-top: 2rem; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def write_report_files(report: Report) -> tuple[Path, Path]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_dir = settings.reports_path
    md_path = report_dir / f"bug-risk-report-{ts}.md"
    html_path = report_dir / f"bug-risk-report-{ts}.html"

    suffix = 2
    while md_path.exists() or html_path.exists():
        md_path = report_dir / f"bug-risk-report-{ts}-{suffix}.md"
        html_path = report_dir / f"bug-risk-report-{ts}-{suffix}.html"
        suffix += 1

    markdown_text = render_markdown(report)
    md_path.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(render_html(markdown_text, f"Bug Risk Report {ts}"), encoding="utf-8")
    return md_path, html_path
