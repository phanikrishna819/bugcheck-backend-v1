"""
Runs every `detection="static"` rule from rules.py against a file's text,
line by line. No LLM call, no rate limit, no cost — this is the pass that
should catch the largest, cheapest share of findings before anything gets
sent to Gemini.

Two rules (event-listener-no-remove, timer-without-cleanup) are whole-file
heuristics rather than per-line matches — a raw count comparison, not a
data-flow check — so they're flagged with confidence="low" and a note that
they need human/LLM confirmation. That's intentional: a regex can tell you
"addEventListener appears 3 times, removeEventListener appears 0 times" but
it cannot tell you *whether* the cleanup happens some other way (e.g. inside
a returned cleanup function using a bound reference). Cheap signal, not
proof — the report says so.
"""
import re
from pathlib import Path

from app.classifiers.rules import Rule, static_rules_for
from app.report.schema import Finding

WHOLE_FILE_HEURISTICS = {"event-listener-no-remove", "timer-without-cleanup"}


def _make_finding(rule: Rule, file_rel: str, line_no: int, evidence: str, confidence="high") -> Finding:
    return Finding(
        rule_id="",  # assigned later during aggregation
        classifier=rule.id,
        title=rule.title,
        severity=rule.base_severity,
        file=file_rel,
        line_start=line_no,
        line_end=line_no,
        evidence=evidence.strip()[:200],
        why_it_matters=rule.title,
        suggested_fix=rule.fix_hint,
        source="static",
        confidence=confidence,
    )


def scan_file_static(file_rel: str, text: str, framework: str, file_ext: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()
    applicable = static_rules_for(framework, file_ext)

    for rule in applicable:
        if rule.id in WHOLE_FILE_HEURISTICS:
            continue  # handled below, once per file
        try:
            compiled = re.compile(rule.pattern)
        except re.error:
            continue
        for i, line in enumerate(lines, start=1):
            if compiled.search(line):
                findings.append(_make_finding(rule, file_rel, i, line))

    # --- whole-file heuristics ---
    if any(r.id == "event-listener-no-remove" for r in applicable):
        adds = len(re.findall(r"\.addEventListener\(", text))
        removes = len(re.findall(r"\.removeEventListener\(", text))
        if adds > removes:
            first_line = next((i for i, l in enumerate(lines, 1) if ".addEventListener(" in l), 1)
            rule = next(r for r in applicable if r.id == "event-listener-no-remove")
            findings.append(_make_finding(
                rule, file_rel, first_line,
                f"{adds} addEventListener call(s) vs {removes} removeEventListener call(s) in this file",
                confidence="low",
            ))

    if any(r.id == "timer-without-cleanup" for r in applicable):
        sets = len(re.findall(r"\bset(?:Interval|Timeout)\s*\(", text))
        clears = len(re.findall(r"\bclear(?:Interval|Timeout)\s*\(", text))
        if sets > clears:
            first_line = next((i for i, l in enumerate(lines, 1) if re.search(r"\bset(Interval|Timeout)\(", l)), 1)
            rule = next(r for r in applicable if r.id == "timer-without-cleanup")
            findings.append(_make_finding(
                rule, file_rel, first_line,
                f"{sets} set(Interval|Timeout) call(s) vs {clears} clear(...) call(s) in this file",
                confidence="low",
            ))

    return findings


def scan_asset_paths(file_rel: str, text: str, workspace_root: Path, file_ext: str) -> list[Finding]:
    """asset-path-added: resolve every quoted relative path that looks like
    an asset reference (src=, url(...), background-image) against the
    uploaded tree; flag the ones that don't exist."""
    from app.classifiers.rules import rule_by_id
    rule = rule_by_id("asset-path-added")
    findings: list[Finding] = []

    patterns = [
        r'src=["\']([^"\':]+\.(?:png|jpe?g|gif|svg|webp|ico|woff2?|ttf))["\']',
        r'url\(["\']?([^"\'()]+\.(?:png|jpe?g|gif|svg|webp|ico|woff2?|ttf))["\']?\)',
    ]
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for pat in patterns:
            for m in re.finditer(pat, line):
                ref = m.group(1)
                if ref.startswith(("http://", "https://", "//", "data:")):
                    continue
                candidate = (Path(file_rel).parent / ref).as_posix() if ref.startswith(".") else ref.lstrip("/")
                if not (workspace_root / candidate).exists():
                    findings.append(_make_finding(rule, file_rel, i, line, confidence="medium"))
    return findings
