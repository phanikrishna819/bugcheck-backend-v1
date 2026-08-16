"""
bugcheck_agent.md's Phase 2 adjusts base severity by blast-radius
(caller-count from coverage-locator) and test-coverage status, then
overrides to HIGH on a failing lint/test run. None of that machinery exists
here yet: coverage-locator needs a real import graph over the *whole*
uploaded app (cheap to add — see README "Extending severity scoring" — but
not wired into this MVP), and there's no test execution step. So findings
are reported at their table-defined base severity, unmodified, and the
verdict is a straightforward "highest severity present" rule instead of the
original's clamped/weighted score.
"""
from app.report.schema import Finding


def compute_counts(findings: list[Finding]) -> dict:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


def compute_verdict(counts: dict) -> str:
    if counts.get("HIGH", 0) > 0:
        return "HIGH_RISK"
    if counts.get("MEDIUM", 0) > 0:
        return "MEDIUM_RISK"
    return "LOW_RISK"


def assign_rule_ids(findings: list[Finding]) -> list[Finding]:
    """QA-<SEV><NN>, sequential within severity, local to this run — same
    scheme as bugcheck_agent.md's Rule IDs section."""
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sev_letter = {"HIGH": "H", "MEDIUM": "M", "LOW": "L"}
    findings_sorted = sorted(findings, key=lambda f: order.get(f.severity, 3))
    counters = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    result = []
    for f in findings_sorted:
        counters[f.severity] += 1
        rule_id = f"QA-{sev_letter[f.severity]}{counters[f.severity]:02d}"
        result.append(f.model_copy(update={"rule_id": rule_id}))
    return result
