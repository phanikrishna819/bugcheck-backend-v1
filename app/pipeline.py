"""
Adapted pipeline, compare against bugcheck_agent.md's "Pipeline (MANDATORY
order)" section:

  original step                          this version
  ------------------------------------   -------------------------------------
  1 detect-environment                   detect_environment() — kept
  2 diff-scope-resolver                  FullAppScope (whole upload) — see
                                          scope/git_diff.py for the diff-mode
                                          extension point
  3 classify diff (Phase 1, read-only)   static_scan + html_checks (free) +
                                          analyze_file's semantic pass (LLM,
                                          rate-limited + capped)
  4 coverage-locator per changed file    NOT implemented — needs an import
                                          graph over the whole app; noted as
                                          a TODO, see README
  5 scoped-lint-and-test                 NOT implemented — needs node_modules
                                          the upload almost never contains;
                                          noted as a TODO
  6 score severity (Phase 2)             severity.py — base severity only,
                                          no blast-radius/coverage adjustment
  7 apply fixes (Phase 3, WRITES CODE)   NOT implemented on purpose — no git
                                          working tree to safely edit/revert,
                                          and the ask was text-format fixes
  8 report-renderer (with-html)          renderer.py — files written to disk,
                                          no local server / "open browser"
"""
from datetime import datetime, timezone
from pathlib import Path

from app.classifiers.html_checks import scan_html_structural
from app.classifiers.static_scan import scan_asset_paths, scan_file_static
from app.config import settings
from app.environment.detect import detect_environment
from app.llm.analyzer import analyze_file
from app.llm.scan_client import llm_available
from app.report.renderer import write_report_files
from app.report.schema import DetectedEnvironment, Finding, Report
from app.report.severity import assign_rule_ids, compute_counts, compute_verdict
from app.scope.full_app import FullAppScope


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _select_files_for_llm(files: list[tuple[str, str, int]], cap: int) -> set[str]:
    """`files` is (rel_path, text, static_finding_count). Prioritize files
    that already have static findings (most likely to have real fix
    material to write about + more likely to have adjacent semantic bugs),
    then largest remaining files, up to `cap`. This is the stand-in for
    "only look at changed files" (diff mode) until GitDiffScope is wired
    in — see README "Why there's a file cap"."""
    with_findings = [f for f in files if f[2] > 0]
    without_findings = [f for f in files if f[2] == 0]
    with_findings.sort(key=lambda f: f[2], reverse=True)
    without_findings.sort(key=lambda f: len(f[1]), reverse=True)
    ordered = with_findings + without_findings
    return {f[0] for f in ordered[:cap]}


def run_pipeline(workspace_root: Path, run_id: str) -> tuple[Report, Path, Path]:
    env = detect_environment(workspace_root)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    notes: list[str] = []

    detected_env = DetectedEnvironment(
        app_name=env.app_name, framework=env.framework, framework_family=env.framework_family,
        pkg_mgr=env.pkg_mgr, test_runner=env.test_runner,
    )

    if env.framework_family == "other":
        finding = Finding(
            rule_id="", classifier="unsupported-framework",
            title=f"Unsupported framework: {env.framework}", severity="LOW",
            file="package.json", line_start=1, line_end=1,
            evidence="dependencies indicate a meta-framework or unrecognized stack",
            why_it_matters="This tool supports plain Angular or plain React only "
                           "(Next.js/Remix/Gatsby/CRA and non-Angular/React stacks are out of scope).",
            suggested_fix="N/A — analysis stops here for this upload.",
            source="static", confidence="high",
        )
        findings = assign_rule_ids([finding])
        counts = compute_counts(findings)
        report = Report(
            run_id=run_id, created_at=created_at, verdict=compute_verdict(counts),
            detected_environment=detected_env, total_files_scanned=0, total_files_llm_reviewed=0,
            counts=counts, findings=findings, notes=notes,
        )
        md_path, html_path = write_report_files(report)
        return report, md_path, html_path

    scope = FullAppScope()
    scanned_files = scope.resolve(workspace_root)

    # --- static pass (free, runs on every file) ---
    per_file_static: dict[str, list[Finding]] = {}
    per_file_text: dict[str, str] = {}
    for abs_path, rel_path in scanned_files:
        text = _read_text(abs_path)
        per_file_text[rel_path] = text
        ext = abs_path.suffix.lower()

        findings = scan_file_static(rel_path, text, env.framework, ext)
        findings += scan_asset_paths(rel_path, text, workspace_root, ext)
        if ext in (".html", ".htm"):
            findings += scan_html_structural(rel_path, text)
        per_file_static[rel_path] = findings

    if not llm_available():
        notes.append("No LLM API key configured — ran static/deterministic checks only, no AI-assisted review.")

    # --- select files for the LLM pass ---
    selection_input = [
        (rel, per_file_text[rel], len(per_file_static[rel])) for rel in per_file_text
    ]
    selected = _select_files_for_llm(selection_input, settings.max_files_for_llm) if llm_available() else set()

    all_findings: list[Finding] = []
    files_llm_reviewed = 0
    for rel_path, static_findings in per_file_static.items():
        ext = Path(rel_path).suffix.lower()
        if rel_path in selected:
            files_llm_reviewed += 1
            enriched, new_findings = analyze_file(
                rel_path, per_file_text[rel_path], env.framework, ext, static_findings,
            )
            all_findings.extend(enriched)
            all_findings.extend(new_findings)
        else:
            all_findings.extend(static_findings)

    if llm_available() and len(per_file_text) > settings.max_files_for_llm:
        notes.append(
            f"AI-assisted review ran on {files_llm_reviewed} of {len(per_file_text)} files "
            f"(capped by MAX_FILES_FOR_LLM={settings.max_files_for_llm} to respect free-tier rate limits); "
            "files with static findings were prioritized. See README for raising this cap or adding "
            "diff-scoped (changed-files-only) mode."
        )

    findings = assign_rule_ids(all_findings)
    counts = compute_counts(findings)
    report = Report(
        run_id=run_id, created_at=created_at, verdict=compute_verdict(counts),
        detected_environment=detected_env, total_files_scanned=len(scanned_files),
        total_files_llm_reviewed=files_llm_reviewed, counts=counts, findings=findings, notes=notes,
    )
    md_path, html_path = write_report_files(report)
    return report, md_path, html_path
