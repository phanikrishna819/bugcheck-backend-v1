"""
PDF fix report ("Buggy — Fix Report") for a scanned workspace.

Uses reportlab (pure-Python wheels, no system libraries) so it works in the
same slim Docker image as the API.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

_SEVERITY_COLORS = {
    "HIGH": colors.HexColor("#b42318"),
    "MEDIUM": colors.HexColor("#b54708"),
    "LOW": colors.HexColor("#027a48"),
}

_ASCII_MAP = {"\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
              "\u201c": '"', "\u201d": '"', "\u2192": "->", "\u00b7": "-"}


def _clean(text) -> str:
    value = str(text or "")
    for source, target in _ASCII_MAP.items():
        value = value.replace(source, target)
    return escape(value)


def _clip(text, limit: int) -> str:
    value = str(text or "")
    return value[:limit] + ("..." if len(value) > limit else "")


def render_fixes_pdf(report) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title="Buggy - Fix Report", author="Buggy",
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BuggyTitle", parent=styles["Title"], fontSize=22, spaceAfter=2))
    styles.add(ParagraphStyle("BuggySub", parent=styles["Normal"], textColor=colors.grey, fontSize=9, spaceAfter=12))
    styles.add(ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle("FindingTitle", parent=styles["Heading3"], fontSize=10.5, spaceBefore=8, spaceAfter=2))
    styles.add(ParagraphStyle("Meta", parent=styles["Normal"], fontSize=8.5, textColor=colors.grey, spaceAfter=2))
    styles.add(ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=12, spaceAfter=3))
    styles.add(ParagraphStyle("BuggyCode", parent=styles["Code"], fontSize=8, leading=10, backColor=colors.HexColor("#f4f4f5")))
    styles.add(ParagraphStyle("Mono", parent=styles["Normal"], fontName="Courier", fontSize=8.5, leading=11))

    env = report.detected_environment
    counts = report.counts or {}
    story = [
        Paragraph("Buggy - Fix Report", styles["BuggyTitle"]),
        Paragraph(_clean(f"Generated {report.created_at} - run {report.run_id}"), styles["BuggySub"]),
    ]

    summary_rows = [
        ["Application", _clean(env.app_name or "(unnamed)"), "Verdict", _clean(report.verdict)],
        ["Framework", _clean(f"{env.framework} ({env.pkg_mgr})"), "Findings",
         _clean(f"{counts.get('HIGH', 0)} high / {counts.get('MEDIUM', 0)} medium / {counts.get('LOW', 0)} low")],
        ["Files scanned", _clean(report.total_files_scanned), "AI-reviewed", _clean(report.total_files_llm_reviewed)],
    ]
    table = Table(summary_rows, colWidths=[28 * mm, 60 * mm, 26 * mm, 60 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#27272a")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d4d4d8")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    findings = list(report.findings or [])
    story.append(Paragraph(f"Needed fixes ({len(findings)})", styles["Section"]))
    if not findings:
        story.append(Paragraph("No issues detected by the static or AI checks.", styles["Body"]))

    for finding in findings:
        severity = (finding.severity or "").upper()
        color = _SEVERITY_COLORS.get(severity, colors.grey)
        heading = Table(
            [[Paragraph(_clean(f"{finding.rule_id or 'QA'}  |  {severity}  |  {finding.title}"),
                        ParagraphStyle("H", parent=styles["FindingTitle"], textColor=color, spaceBefore=0, spaceAfter=0))]],
            colWidths=[174 * mm],
        )
        heading.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#e4e4e7"))]))
        story.append(heading)
        line = finding.line_start if finding.line_end in (None, finding.line_start) else f"{finding.line_start}-{finding.line_end}"
        story.append(Paragraph(_clean(f"{finding.file}:{line}  (source: {finding.source}, confidence: {finding.confidence})"),
                               styles["Meta"]))
        if finding.evidence:
            story.append(Paragraph(_clean(_clip(finding.evidence, 700)), styles["Code"]))
            story.append(Spacer(1, 3))
        story.append(Paragraph("<b>Why it matters:</b> " + _clean(finding.why_it_matters), styles["Body"]))
        story.append(Paragraph("<b>Suggested fix:</b> " + _clean(finding.suggested_fix), styles["Body"]))

    if report.notes:
        story.append(Paragraph("Notes", styles["Section"]))
        for note in report.notes:
            story.append(Paragraph(_clean(f"- {note}"), styles["Body"]))

    def _footer(canvas, doc_ref):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(18 * mm, 10 * mm, "Buggy - static + AI-assisted review")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc_ref.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
