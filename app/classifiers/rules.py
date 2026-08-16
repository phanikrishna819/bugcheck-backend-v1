"""
This table is a direct port of the classifier list in bugcheck_agent.md
(Phase 1 "Generic" + "Framework overlay" tables), restructured as data.

Why port it as data instead of leaving it as agent-instructions:
  - `detection="static"` rules get a real regex and run for free in
    static_scan.py / html_checks.py, no LLM call needed.
  - `detection="llm"` rules are semantic (data-flow, correctness judgment)
    and can't be reliably regexed — they're handed to Gemini as the rule
    subset relevant to each file (see llm/analyzer.py), along with the
    matching `fix_hint` so its suggested fixes track the original recipes
    in bugcheck_agent.md's Phase 3 table instead of improvising.

Severity here is the *base* severity from the original table. This MVP does
not implement Phase 2's blast-radius/coverage adjustment (that needs
coverage-locator + caller-count, which needs a real dependency graph over
the uploaded app) — base severity is reported as-is. See README.
"""
from dataclasses import dataclass
from typing import Optional

HIGH, MED, LOW = "HIGH", "MEDIUM", "LOW"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    base_severity: str
    framework: str          # "generic" | "angular" | "react"
    file_types: tuple        # subset of ("js", "html", "css")
    detection: str            # "static" | "llm"
    fix_hint: str
    pattern: Optional[str] = None  # regex, only set when detection == "static"


RULES: list[Rule] = [
    # ---- statically detectable (regex / parser based) ----
    Rule("console-or-debugger", "console/debugger left in code", LOW, "generic", ("js",), "static",
         "Delete. Don't replace with a logger unless neighboring files already use one.",
         pattern=r"\b(console\.(log|debug|warn|info)|debugger)\s*\("),
    Rule("any-cast-introduced", "new `as any` / `: any` / ts-ignore", LOW, "generic", ("js",), "static",
         "Replace with a real type, or narrow with a type guard.",
         pattern=r"(:\s*any\b|as\s+any\b|@ts-ignore|@ts-expect-error)"),
    Rule("secret-like", "hardcoded token/key/password", HIGH, "generic", ("js", "html", "css"), "static",
         "Move to an env var / secret manager; never commit the literal value.",
         pattern=r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][A-Za-z0-9_\-\.]{12,}['\"]"),
    Rule("target-blank-no-rel", "target=\"_blank\" without rel", MED, "generic", ("js",), "static",
         'Append rel="noopener noreferrer". (HTML files are checked by the parser-based pass in '
         'html_checks.py instead of this regex — this entry only covers target="_blank" written inline '
         'in .jsx/.tsx, so the two passes never double-count the same finding on a real .html file.)',
         pattern=r'target=["\']_blank["\'](?!(?:(?!\btarget=).)*rel=["\'][^"\']*noopener)'),
    Rule("storage-write-unstringified", "localStorage/sessionStorage write without JSON.stringify", HIGH,
         "generic", ("js",), "static",
         "Wrap writes with JSON.stringify; wrap reads with try { JSON.parse } catch { fallback }.",
         pattern=r"(localStorage|sessionStorage)\.setItem\([^,]+,\s*(?!JSON\.stringify)[^)]*\)"),
    Rule("cookie-insecure-flags", "document.cookie write missing Secure/SameSite", HIGH, "generic", ("js",),
         "static",
         'Append "; Secure; SameSite=Strict; Path=/". Auth cookies: recommend server-set HttpOnly instead.',
         pattern=r"document\.cookie\s*=\s*(?!.*(Secure|SameSite))"),
    Rule("html-unclosed-tag", "unclosed HTML tag", MED, "generic", ("html",), "static", "Close at the correct nesting depth."),
    Rule("html-duplicate-id", "duplicate id in the same document", MED, "generic", ("html",), "static",
         "Rename one id and update every for/aria-labelledby reference to it."),
    Rule("html-invalid-nesting", "invalid element nesting (e.g. block inside <p>)", MED, "generic", ("html",),
         "static", "Replace the outer element with a valid container; don't paper over it with display:contents."),
    Rule("image-missing-alt", "<img> without alt", MED, "generic", ("html",), "static",
         'Add a descriptive alt=""..."". Use alt="" only for decorative images.'),
    Rule("image-missing-dimensions", "<img> without width/height or aspect-ratio", LOW, "generic", ("html",),
         "static", "Add explicit width+height, or CSS aspect-ratio for responsive images."),
    Rule("asset-path-added", "referenced asset path does not exist on disk", HIGH, "generic",
         ("js", "html", "css"), "static", "Fix the path to match a real file under the upload, or remove the reference."),
    Rule("event-listener-no-remove", "addEventListener without a matching removeEventListener in file", MED,
         "generic", ("js",), "static",
         "Keep a stable handler reference; add and remove with the same reference.",
         pattern=r"\.addEventListener\("),
    Rule("timer-without-cleanup", "setInterval/setTimeout with no matching clear in file", MED, "generic",
         ("js",), "static",
         "Store the timer id and clear it in the component/service teardown (ngOnDestroy / effect cleanup).",
         pattern=r"\bset(Interval|Timeout)\s*\("),
    Rule("ngfor-missing-trackby", "*ngFor without trackBy", MED, "angular", ("html",), "static",
         "Add a trackBy function and declare it in the component."),
    Rule("missing-key-map", "React .map() rendering JSX without a key prop", MED, "react", ("js",), "static",
         "Add key={item.id ?? index}, preferring a stable id over the array index."),
    Rule("css-media-missing-unit", "@media (min/max)-width|height value missing a CSS unit", LOW, "generic",
         ("css",), "static",
         "Add the unit (usually px) to the media feature value, e.g. change (max-width: 768) to "
         "(max-width: 768px) — a bare number here is invalid and browsers silently ignore the whole rule.",
         pattern=r"@media\s*\(\s*(?:min|max)-(?:width|height)\s*:\s*[1-9]\d*\s*\)"),

    # ---- semantic — requires an LLM pass (data-flow / correctness judgment) ----
    Rule("control-flow-added", "new conditional/branch logic", MED, "generic", ("js",), "llm",
         "Verify all branches are reachable and tested; add a missing else/default if the branch is incomplete."),
    Rule("endpoint-added", "new network call without an error/loading branch", HIGH, "generic", ("js",), "llm",
         "Add a neighbor-standard error UI branch and a loading state if similar calls in the file have one."),
    Rule("subscribe-leak", "RxJS .subscribe()/useEffect subscription without cleanup", MED, "generic", ("js",),
         "llm", "Angular: takeUntilDestroyed()/async pipe. React: return a cleanup fn from useEffect."),
    Rule("effect-missing-deps", "useEffect/useMemo/useCallback with wrong/missing deps", MED, "react", ("js",),
         "llm", "Add the missing dependency; if that causes a loop, wrap the value in useCallback/useMemo instead."),
    Rule("stale-closure-event-handler", "handler captures state without re-registering", MED, "react", ("js",),
         "llm", "Use a ref-proxy pattern, or add the handler to the effect's dependency array."),
    Rule("state-setter-in-render", "React setState called unconditionally during render", HIGH, "react", ("js",),
         "llm", "Move the setter into an effect, event handler, or compute the value with useMemo instead."),
    Rule("object-literal-context-value", "inline object/array/fn passed as Context.Provider value", MED, "react",
         ("js",), "llm", "Hoist to useMemo(() => ({...}), [deps]); wrap callbacks in useCallback."),
    Rule("unsanitized-html-sink", "innerHTML / dangerouslySetInnerHTML fed non-literal data", HIGH, "generic",
         ("js",), "llm", "Sanitize with DOMPurify before writing to the sink (DomSanitizer on Angular)."),
    Rule("a11y-interactive-element", "click/keydown handler on a non-interactive element", MED, "generic",
         ("html", "js"), "llm", 'Prefer <button type="button">, or add role="button" + tabindex="0" + a keydown handler.'),
    Rule("form-submit-unvalidated", "submit calls the API without a validity gate", HIGH, "generic", ("js",),
         "llm", "Gate the submit handler on the form library's validity state before calling the API."),
    Rule("reactive-form-mismatch", "template form control not declared in the form model (or vice versa)", HIGH,
         "generic", ("js", "html"), "llm", "Add/remove the control so the template and the form model agree."),
    Rule("swallowed-catch", "empty or log-only catch block", MED, "generic", ("js",), "llm",
         "Surface the error to the user via the app's existing error/toast pattern, or rethrow."),
    Rule("missing-http-error-branch", "new HTTP call without an error UI when neighbors have one", MED, "generic",
         ("js",), "llm", "Add the same error-state pattern used by nearby HTTP calls in the file."),
    Rule("missing-loading-state", "new async read without a loading UI when neighbors have one", LOW, "generic",
         ("js",), "llm", "Add a loading flag/spinner consistent with neighboring async reads."),
    Rule("focus-lost-on-conditional", "conditional render removes the focused element without restoring focus",
         MED, "generic", ("js",), "llm", "Capture and restore focus to a sibling or the container on toggle."),
    Rule("unguarded-query-param", "route/query param read without a fallback", MED, "generic", ("js",), "llm",
         "Use ?? <default> or a schema validator's .default()/.catch()."),
    Rule("floating-promise", "promise-returning call not awaited/handled", MED, "generic", ("js",), "llm",
         "await it, chain .catch(), or explicitly discard with void."),
    Rule("direct-state-mutation", "state/reducer mutated in place instead of replaced", HIGH, "generic", ("js",),
         "llm", "React: build a new array/object. Redux/NgRx: keep using Immer's createSlice."),
    Rule("double-submit-guard-missing", "submit handler has no in-flight/disabled guard", MED, "generic", ("js",),
         "llm", "Track a submitting flag, disable the control while true, clear it in finally."),
    Rule("autofill-onchange-gap", "controlled input has value but no onChange", HIGH, "react", ("js",), "llm",
         "Add the missing onChange handler that updates the bound state."),
    Rule("websocket-no-reconnect", "WebSocket/EventSource with no reconnect or stale-UI handling", MED, "generic",
         ("js",), "llm", "Add onerror/onclose handling with backoff, and surface connection state to the UI."),
    Rule("polling-no-stop", "recursive setTimeout polling with no cancel path", MED, "generic", ("js",), "llm",
         "Add an AbortController/cancel flag checked before each re-schedule."),
    Rule("abort-controller-missing", "re-firable fetch/axios call with no cancellation", MED, "generic", ("js",),
         "llm", "React: AbortController + signal, abort in the effect cleanup. Angular: switchMap."),
    Rule("debounce-missing", "input change triggers HTTP/heavy work with no debounce", MED, "generic", ("js",),
         "llm", "Add debounce/throttle consistent with how neighboring inputs in the file behave."),
    Rule("unsafe-date-parse", "new Date(non-ISO-string) — timezone-dependent parsing", MED, "generic", ("js",),
         "llm", "Use Date.UTC(y, m-1, d) or the date library already used elsewhere in the app."),
    Rule("circular-import-risk", "new import closes a cycle between changed files", HIGH, "generic", ("js",),
         "llm", "Extract the shared symbol into a third module both sides import."),
    Rule("env-var-no-fallback", "env var read at runtime with no fallback", MED, "generic", ("js",), "llm",
         "Add ?? <literal> for non-secrets; add a build-time assertion for required values."),
    Rule("file-upload-unvalidated", "<input type=file> read without size/type checks", HIGH, "generic", ("js",),
         "llm", "Guard on file size and MIME type before using the file."),
    Rule("paste-unsanitized", "pasted HTML written to a sink without sanitizing", HIGH, "generic", ("js",), "llm",
         "Accept text/plain only, or sanitize with DOMPurify before writing HTML."),
    Rule("optimistic-update-no-rollback", "optimistic UI update with no rollback on failure", MED, "generic",
         ("js",), "llm", "Snapshot previous state and restore it in the .catch()/onError path."),
    Rule("shared-mutable-export", "module-level exported object mutated by multiple consumers", HIGH, "generic",
         ("js",), "llm", "Export a factory function instead of a shared mutable object."),
    Rule("regex-catastrophic-backtracking", "regex with nested quantifiers applied to user input", MED, "generic",
         ("js",), "llm", "Rewrite with atomic/anchored groups and bound input length before matching."),
    Rule("rxjs-share-missing", "multi-subscribed Observable without shareReplay", MED, "angular", ("js",), "llm",
         "Add .pipe(shareReplay({bufferSize:1, refCount:true})) at the service boundary."),
    Rule("angular-zone-escape", "runOutsideAngular write not wrapped back in ngZone.run", MED, "angular", ("js",),
         "llm", "Wrap the UI-affecting write in ngZone.run(...), or migrate to Signals."),
    Rule("micro-frontend-global-style", "unscoped global CSS rule in a repo that otherwise scopes styles", MED,
         "generic", ("css",), "llm", "Move the rule into a scoped stylesheet or prefix it with the app's root class."),
    Rule("rules-of-hooks", "React hook called conditionally or outside a component/hook", HIGH, "react", ("js",),
         "llm", "Move the hook call to the top level of the component/hook, unconditionally."),
    Rule("component-mutating-props", "component mutates a prop it received", HIGH, "react", ("js",), "llm",
         "Copy the prop into local state or a derived value instead of mutating it."),
]


def rules_for(framework: str, file_ext: str) -> list[Rule]:
    """Rules whose framework tag matches ('generic' always matches) and
    whose file_types cover this extension."""
    bucket = "html" if file_ext in (".html", ".htm") else "css" if file_ext in (
        ".css", ".scss", ".sass", ".less") else "js"
    return [
        r for r in RULES
        if (r.framework == "generic" or r.framework == framework) and bucket in r.file_types
    ]


def static_rules_for(framework: str, file_ext: str) -> list[Rule]:
    return [r for r in rules_for(framework, file_ext) if r.detection == "static" and r.pattern]


def llm_rules_for(framework: str, file_ext: str) -> list[Rule]:
    return [r for r in rules_for(framework, file_ext) if r.detection == "llm"]


def rule_by_id(rule_id: str) -> Optional[Rule]:
    return next((r for r in RULES if r.id == rule_id), None)
