from typing import Optional
from pydantic import BaseModel


class Finding(BaseModel):
    rule_id: str                 # e.g. QA-H01 — assigned at aggregation time
    classifier: str              # e.g. "console-or-debugger"
    title: str
    severity: str                # HIGH | MEDIUM | LOW
    file: str                    # workspace-relative path
    line_start: int
    line_end: Optional[int] = None
    evidence: str                 # short real-code excerpt
    why_it_matters: str
    suggested_fix: str
    source: str                    # "static" | "llm"
    confidence: str = "medium"      # "low" | "medium" | "high" — static=high, llm-reported


class DetectedEnvironment(BaseModel):
    app_name: Optional[str]
    framework: str
    framework_family: str
    pkg_mgr: str
    test_runner: Optional[str]


class Report(BaseModel):
    run_id: str
    created_at: str
    verdict: str                    # LOW_RISK | MEDIUM_RISK | HIGH_RISK
    verdict_suffix: str = "(analysis-only)"
    detected_environment: DetectedEnvironment
    total_files_scanned: int
    total_files_llm_reviewed: int
    counts: dict                    # {"HIGH": n, "MEDIUM": n, "LOW": n}
    findings: list[Finding]
    notes: list[str] = []            # e.g. "unsupported framework", "LLM skipped: no API key"
