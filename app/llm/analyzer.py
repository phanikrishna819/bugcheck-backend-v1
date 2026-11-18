"""
One Gemini call per file does double duty, to stay inside free-tier RPM:

  1. For every static finding already found in this file, write a real
     `why_it_matters` sentence and a concrete `suggested_fix` grounded in
     the actual code (the regex pass only has a generic fix_hint per rule).
  2. Look for additional bugs from the *semantic* rule subset for this
     file's framework/type (rules.py `detection == "llm"`) — the ones a
     regex genuinely can't judge (missing effect deps, unvalidated
     submits, etc.) — and return them as new findings.

This mirrors bugcheck_agent.md's intent (classify, then recipe-based fix)
but skips its Phase 3 (WRITES CODE / auto-apply / re-run tests / git
revert-on-regression loop) entirely: there's no live git working tree here
to safely edit and roll back, and the user asked for fixes "in text
format", not applied changes. See README for how to extend this into an
apply-and-verify mode once the backend owns a real checkout.
"""
import json

from app.classifiers.rules import llm_rules_for, rule_by_id
from app.llm.scan_client import generate_json
from app.report.schema import Finding

MAX_CHARS_PER_FILE = 12000

SYSTEM_PROMPT = """You are a meticulous senior frontend code reviewer for Angular and React \
applications. You review real source files and report only bugs you can point to with an exact \
line number and a short quoted excerpt of the ACTUAL code — never a generic or invented example. \
If a rule doesn't clearly apply to what's actually in the file, leave it out; do not pad the \
output with generic advice. Respond with a single JSON object matching the schema described in \
the user message, and nothing else — no markdown fences, no commentary."""


def _build_user_prompt(file_rel: str, text: str, framework: str, llm_rules, static_findings: list[Finding]) -> str:
    truncated = len(text) > MAX_CHARS_PER_FILE
    body = text[:MAX_CHARS_PER_FILE]

    rules_block = "\n".join(
        f'- "{r.id}" ({r.base_severity}): {r.title}. Typical fix: {r.fix_hint}' for r in llm_rules
    )
    static_block = "\n".join(
        f'- classifier="{f.classifier}" line={f.line_start} evidence="{f.evidence}"'
        for f in static_findings
    ) or "(none)"

    return f"""Framework: {framework}
File: {file_rel}{" (truncated to first %d chars)" % MAX_CHARS_PER_FILE if truncated else ""}

--- FILE CONTENT (line numbers are 1-based, matching the file as shown) ---
{body}
--- END FILE CONTENT ---

TASK 1 — write real fix text for these already-detected findings in this file:
{static_block}

TASK 2 — additionally check the file against ONLY this rule subset and report genuinely new bugs you can \
prove from the code above (do not repeat anything already listed in TASK 1's findings):
{rules_block}

Respond with JSON matching exactly this shape:
{{
  "static_fix_ups": [
    {{"classifier": "<one of the classifiers listed above>", "line": <int>,
      "why_it_matters": "<one sentence, end-user impact>",
      "suggested_fix": "<concrete code-level fix, may include a short snippet>"}}
  ],
  "new_findings": [
    {{"classifier": "<id from TASK 2's rule subset>", "line_start": <int>, "line_end": <int>,
      "evidence": "<short exact quote from the file above>",
      "why_it_matters": "<one sentence, end-user impact>",
      "suggested_fix": "<concrete code-level fix>",
      "confidence": "low" | "medium" | "high"}}
  ]
}}
If there is nothing to add for a task, return an empty list for it."""


def analyze_file(file_rel: str, text: str, framework: str, file_ext: str,
                  static_findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Returns (enriched_static_findings, new_llm_findings). Falls back to
    the unmodified static findings + no new findings if the LLM is
    unavailable or the response can't be parsed — a run should always
    degrade gracefully to static-only, never crash."""
    llm_rules = llm_rules_for(framework, file_ext)
    if not llm_rules and not static_findings:
        return static_findings, []

    prompt = _build_user_prompt(file_rel, text, framework, llm_rules, static_findings)
    parsed = generate_json(SYSTEM_PROMPT, prompt)

    if not isinstance(parsed, dict):
        return static_findings, []

    # --- apply fix-ups to existing static findings ---
    fixups_by_key = {}
    for fu in parsed.get("static_fix_ups", []) or []:
        try:
            key = (fu["classifier"], int(fu["line"]))
            fixups_by_key[key] = fu
        except (KeyError, TypeError, ValueError):
            continue

    enriched = []
    for f in static_findings:
        fu = fixups_by_key.get((f.classifier, f.line_start))
        if fu:
            f = f.model_copy(update={
                "why_it_matters": fu.get("why_it_matters", f.why_it_matters),
                "suggested_fix": fu.get("suggested_fix", f.suggested_fix),
            })
        enriched.append(f)

    # --- new semantic findings ---
    new_findings = []
    for nf in parsed.get("new_findings", []) or []:
        rule = rule_by_id(nf.get("classifier", ""))
        if rule is None:
            continue  # model invented a classifier — drop rather than trust it
        try:
            new_findings.append(Finding(
                rule_id="",
                classifier=rule.id,
                title=rule.title,
                severity=rule.base_severity,
                file=file_rel,
                line_start=int(nf.get("line_start", 1)),
                line_end=int(nf.get("line_end", nf.get("line_start", 1))),
                evidence=str(nf.get("evidence", ""))[:300],
                why_it_matters=str(nf.get("why_it_matters", rule.title)),
                suggested_fix=str(nf.get("suggested_fix", rule.fix_hint)),
                source="llm",
                confidence=nf.get("confidence", "medium") if nf.get("confidence") in ("low", "medium", "high") else "medium",
            ))
        except (TypeError, ValueError):
            continue

    return enriched, new_findings
