"""
The html-unclosed-tag / html-duplicate-id / html-invalid-nesting rules
need actual tag-stack tracking, not a regex — this module uses stdlib
html.parser for that, which keeps us dependency-free.

Angular templates (*.html alongside a *.component.ts) use the same HTML
grammar plus Angular template syntax (*ngFor, [binding], (event)) which
Python's html.parser tolerates fine as attribute soup — we don't need to
understand Angular's template DSL to check tag balance or duplicate ids.
"""
from html.parser import HTMLParser

from app.classifiers.rules import rule_by_id
from app.report.schema import Finding

# HTML5 void elements never need a closing tag
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

BLOCK_ELEMENTS = {
    "div", "p", "section", "article", "header", "footer", "nav", "aside",
    "ul", "ol", "table", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "figure",
}


class _StructuralChecker(HTMLParser):
    def __init__(self, file_rel: str):
        super().__init__(convert_charrefs=True)
        self.file_rel = file_rel
        self.findings: list[Finding] = []
        self.stack: list[tuple[str, int]] = []   # (tag, line)
        self.seen_ids: dict[str, int] = {}

    def _mk(self, classifier: str, line: int, evidence: str, confidence="medium") -> Finding:
        rule = rule_by_id(classifier)
        return Finding(
            rule_id="", classifier=rule.id, title=rule.title, severity=rule.base_severity,
            file=self.file_rel, line_start=line, line_end=line, evidence=evidence[:200],
            why_it_matters=rule.title, suggested_fix=rule.fix_hint, source="static",
            confidence=confidence,
        )

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        attrs_dict = dict(attrs)

        # duplicate id
        el_id = attrs_dict.get("id")
        if el_id:
            if el_id in self.seen_ids:
                self.findings.append(self._mk(
                    "html-duplicate-id", line,
                    f'id="{el_id}" also used on line {self.seen_ids[el_id]}',
                ))
            else:
                self.seen_ids[el_id] = line

        # missing alt / dimensions on <img>
        if tag == "img":
            if "alt" not in attrs_dict:
                self.findings.append(self._mk("image-missing-alt", line, "<img> without alt attribute"))
            if not ({"width", "height"} <= attrs_dict.keys()) and "aspect-ratio" not in (attrs_dict.get("style") or ""):
                self.findings.append(self._mk(
                    "image-missing-dimensions", line, "<img> without width/height or aspect-ratio", confidence="low",
                ))

        # target=_blank without rel=noopener
        if attrs_dict.get("target") == "_blank":
            rel = attrs_dict.get("rel", "")
            if "noopener" not in rel:
                self.findings.append(self._mk("target-blank-no-rel", line, f'<{tag} target="_blank" rel="{rel}">'))

        # *ngFor without trackBy (Angular templates)
        ngfor = next((v for k, v in attrs_dict.items() if k in ("*ngfor",)), None)
        if ngfor is not None and "trackby" not in ngfor.lower():
            self.findings.append(self._mk("ngfor-missing-trackby", line, f'*ngFor="{ngfor}"'))

        # invalid nesting — limited, high-confidence ruleset only
        if self.stack:
            parent_tag, _ = self.stack[-1]
            if parent_tag == "p" and tag in BLOCK_ELEMENTS:
                self.findings.append(self._mk(
                    "html-invalid-nesting", line, f"<{tag}> nested inside <p> (block inside inline-context element)",
                ))
            if parent_tag == "button" and tag in ("a", "button"):
                self.findings.append(self._mk(
                    "html-invalid-nesting", line, f"<{tag}> nested inside <button>",
                ))
            if parent_tag in ("ul", "ol") and tag != "li":
                self.findings.append(self._mk(
                    "html-invalid-nesting", line, f"<{tag}> as a direct child of <{parent_tag}> (expected <li>)",
                ))

        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, line))

    def handle_startendtag(self, tag, attrs):
        # self-closed e.g. <div />  — treat starttag logic but don't push to stack
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][0] == tag and self.stack[-1][1] == self.getpos()[0]:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        # tag mismatch: pop up the stack looking for a matching open tag
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                unclosed = self.stack[idx + 1:]
                for utag, uline in unclosed:
                    self.findings.append(self._mk(
                        "html-unclosed-tag", uline, f"<{utag}> opened here is never closed before </{tag}>",
                    ))
                del self.stack[idx:]
                return
        # closing tag with no matching open tag at all — ignore (likely a
        # parser artifact from Angular/JSX-flavoured syntax we don't fully
        # understand); avoid false positives rather than guess.

    def close(self):
        super().close()
        for utag, uline in self.stack:
            self.findings.append(self._mk("html-unclosed-tag", uline, f"<{utag}> is never closed"))


def scan_html_structural(file_rel: str, text: str) -> list[Finding]:
    checker = _StructuralChecker(file_rel)
    try:
        checker.feed(text)
        checker.close()
    except Exception:
        # Malformed input the parser can't recover from — don't crash the
        # whole run over one file; just skip structural checks for it.
        return checker.findings
    return checker.findings
