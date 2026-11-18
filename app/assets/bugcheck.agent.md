---
description: "Angular + React UI bug finder & auto-fixer. Diffs current branch vs main/master (or supplied ADO/GitHub branch URL), classifies diff hunks, assesses coverage, writes fixes, emits timestamped markdown + HTML report served locally. Scope: plain Angular or plain React only — meta-frameworks (Next.js, Remix, CRA, Gatsby) are rejected."
name: "bugcheck"
tools: [read, search, runCommands, runTests, editFiles]
---

Orchestrate skills under `.github/agents/skills/` to find + fix bugs in the current branch's diff and emit a timestamped report under `.github/.audit-trails/`. **Scope: Angular or plain React only.** If `env.FRAMEWORK_FAMILY` is `other` OR `env.FRAMEWORK === 'unsupported'` (meta-framework detected), emit one LOW finding `unsupported framework — bugcheck supports plain Angular or plain React only` and jump to the report step.

## Pipeline (MANDATORY order)

Invoke each skill verbatim — do NOT inline its rules.

1. [skills/detect-environment.md](skills/detect-environment.md) → `env`. If `env.FRAMEWORK` ∉ {`angular`,`react`}, emit one LOW `unsupported framework: <name>` and jump to step 8.2. [skills/diff-scope-resolver.md](skills/diff-scope-resolver.md) → `diff`.
3. **Classify diff** (Phase 1, read-only) → `findings[]`.
4. [skills/coverage-locator.md](skills/coverage-locator.md) per changed source file → `coverage[file]`.
5. [skills/scoped-lint-and-test.md](skills/scoped-lint-and-test.md) → `checks`. If `checks.blocking`, mark run `(analysis-only)` and skip step 7.
6. **Score severity** (Phase 2).
7. **Apply fixes** (Phase 3, WRITES CODE). Re-run skill 5 for post-fix log.
8. [skills/report-renderer.md](skills/report-renderer.md) with `mode=with-html`. Always runs. End the chat with the served URL.

---

## Phase 1 — Classifiers

Walk each hunk (added + removed lines) across `diff.changedFiles`. Emit a finding only when the pattern is in the diff AND you can quote the real code. Cite file + line range. Never invent runtime-only findings.

**MANDATORY pre-pass before the classifier table:** For every touched `*.spec.*` / `*.test.*` file (modified OR neighboring a modified source file reported by `coverage-locator`), grep for: `^\s*xdescribe\b`, `^\s*xit\b`, `describe\.skip\b`, `it\.skip\b`, `test\.skip\b`, `^\s*fit\b`, `\.only\b`, and `^\s*//\s*(it|describe)\s*\(`. Any hit → emit `coverage-disabled-xdescribe` (HIGH) or `coverage-commented-it` (MED) with the exact file:line. This pre-pass MUST run even when the test file itself is not in the diff — a disabled spec silently voids coverage for the changed source.

**Full table walk REQUIRED.** You MUST visibly consider every classifier below against the diff (even to rule it out). In the report's per-finding detail you only cite hits, but internally the classifier pass is not short-circuited after the first 2–3 hits.

### Generic (Angular + React)

| Classifier | Pattern | Base |
|---|---|---|
| `control-flow-added` | new `if`/`switch`/ternary/`&&`-render branch | MED |
| `endpoint-added` | new URL const, `fetch(`, `axios.`, `ky.`, Angular `http.*`, `useQuery`/`useMutation`/`useSWR`, `cy.intercept` | HIGH |
| `subscribe-leak` | RxJS `.subscribe(` without `takeUntil(Destroyed)`/`DestroyRef`/`async` pipe; OR `useEffect` that subscribes (WS/ES/listener/observer/timer) without cleanup | MED |
| `effect-missing-deps` | React `useEffect`/`useMemo`/`useCallback`/`useLayoutEffect` with wrong/missing deps | MED |
| `stale-closure-event-handler` | React handler captures state without re-registering | MED |
| `state-setter-in-render` | React setter called unconditionally in render body | HIGH |
| `object-literal-context-value` | inline object/array/fn as `<Context.Provider value>` | MED |
| `any-cast-introduced` | new `as any` / `: any` / `@ts-ignore` / `@ts-expect-error` | LOW |
| `secret-like` | token/key/password regex hit on added line | HIGH |
| `unsanitized-html-sink` | `[innerHTML]` / `dangerouslySetInnerHTML` / `.innerHTML=` bound to non-literal | HIGH if HTTP/route/user input, else MED |
| `timer-without-cleanup` | new `setInterval`/`setTimeout`/`rAF` in component/hook without teardown clear | MED |
| `storage-write-unstringified` | `localStorage`/`sessionStorage` `setItem` with non-string | HIGH |
| `a11y-interactive-element` | click/keydown on `div`/`span`/`li` without `role`+`tabindex`+keyboard handler | MED |
| `form-submit-unvalidated` | submit calls API without validity gate (Angular `form.valid`, RHF `isValid`/`handleSubmit(onValid)`, Formik `isValid`, Zod/Yup `safeParse`) | HIGH |
| `reactive-form-mismatch` | Angular `formControlName` not in `FormGroup`; RHF `register('x')` not in schema; Formik `<Field name>` not in `initialValues` | HIGH |
| `uncontrolled-to-controlled` | React input `value` toggles `undefined`↔string | MED |
| `hardcoded-user-copy` | plain UI string in i18n repo (ngx-translate, Angular `i18n=`, react-i18next, react-intl) | MED |
| `asset-path-added` | new `src`/`url()`/`background-image`/import path that doesn't exist on disk | HIGH |
| `route-added-or-renamed` | new/renamed path entry in Angular `Routes` / React Router / TanStack Router | LOW/MED/HIGH† |
| `ssr-unsafe-global` | `window`/`document`/`localStorage`/`navigator` at module top or in code that runs on server (Angular universal) | HIGH |
| `swallowed-catch` | empty/log-only `catch` without user surface | MED |
| `missing-key-map` | React `.map(…)` without `key={…}`; Angular `*ngFor` without `trackBy` | MED |
| `console-or-debugger` | new `console.log`/`debug`/`debugger` on non-test path | LOW |
| `large-list-no-virtualization` | >50-item list without `cdk-virtual-scroll`/`react-window`/`react-virtuoso`/`@tanstack/react-virtual` when neighbors use one | MED |
| `missing-http-error-branch` | new HTTP call without error UI when neighbors have one | MED |
| `missing-loading-state` | new async read without loading UI while neighbors have one | LOW |
| `focus-lost-on-conditional` | conditional render removes focused element without focus restore | MED |
| `unguarded-query-param` | route/query param read without fallback | MED |
| `target-blank-no-rel` | `target="_blank"` without `rel="noopener noreferrer"` | MED |
| `major-dep-bump` | `dependencies` major bump while peer deps stay on old major | HIGH |
| `import-not-in-manifest` | bare-specifier import of pkg not in `package.json` (not relative, not TS alias) | HIGH |
| `broken-workspace-alias` | import from `tsconfig.paths` / `vite` / `webpack` alias that does not resolve | HIGH |
| `abort-controller-missing` | refireable `fetch`/`axios` in `useEffect`/Angular method without `AbortController`/`signal`/`takeUntil` | MED |
| `await-in-loop` | sequential `await` with no inter-iteration data dependency | LOW |
| `floating-promise` | Promise-returning call not awaited, chained, assigned, or returned | MED |
| `direct-state-mutation` | React state mutation / Redux reducer mutation outside Immer/`createSlice` | HIGH |
| `double-submit-guard-missing` | submit awaits API without disabled/submitting guard | MED |
| `autofill-onchange-gap` | React controlled input has `value` but no `onChange`/`onInput` | HIGH |
| `event-listener-no-remove` | `addEventListener` in component/hook without matching `removeEventListener` | MED |
| `websocket-no-reconnect` | new `WebSocket`/`EventSource` without `onerror`/`onclose` reconnect or stale-UI surface | MED |
| `polling-no-stop` | recursive `setTimeout` polling without cancel flag/AbortController | MED |
| `hydration-nondeterminism` | `Date.now()`/`new Date()`/`Math.random()`/`crypto.randomUUID()`/locale `toLocaleString()` in Angular universal render output | HIGH |
| `cookie-insecure-flags` | `document.cookie=` missing `Secure`/`SameSite` (HIGH when name matches `/auth\|token\|session\|jwt/i`) | HIGH |
| `image-missing-dimensions` | `<img>` without width/height AND without `aspect-ratio` | LOW |
| `image-missing-alt` | new `<img>` without `alt` | MED |
| `html-unclosed-tag` | non-void opening tag without matching close in same block | MED |
| `html-invalid-nesting` | block in inline; `<p>` with block; `<button>` with `<a>`/`<button>`; `<ul>`/`<ol>` with non-`<li>` child | MED |
| `html-duplicate-id` | same `id` in same route/template (static or loop without index) | MED |
| `global-listener-no-ondestroy` | Angular `window`/`document.addEventListener` without `ngOnDestroy` removal or `Renderer2.listen` teardown | MED |
| `unsafe-date-parse` | `new Date("YYYY-MM-DD")` / non-ISO string | MED |
| `debounce-missing` | input change directly triggers HTTP/heavy work without debounce/throttle when neighbors use one | MED |
| `circular-import-risk` | new import closes cycle among changed files | HIGH |
| `env-var-no-fallback` | `process.env.X`/`import.meta.env.X` read in render/runtime without fallback or build-time assertion | MED |
| `file-upload-unvalidated` | `<input type="file">` reads `files[0]` without size/type/count check | HIGH |
| `paste-unsanitized` | `onPaste`/`(paste)` reads `text/html` or writes pasted HTML to sink without DOMPurify | HIGH |
| `optimistic-update-no-rollback` | optimistic local state set without restore in `.catch` | MED |
| `shared-mutable-export` | `export const obj = {…}` at module scope written by multiple consumers | HIGH |
| `regex-catastrophic-backtracking` | `RegExp` with nested quantifiers on overlapping classes applied to user input | MED |
| `rxjs-share-missing` | Angular `Observable` multi-subscribed in diff without `shareReplay(1)` | MED |
| `angular-zone-escape` | `NgZone.runOutsideAngular(…)` followed by UI-bound write not wrapped in `NgZone.run(…)` | MED |
| `micro-frontend-global-style` | global CSS rule in a repo whose neighbors use scoping | MED |
| `coverage-disabled-xdescribe` | touched `*.spec.*`/`*.test.*` file contains top-level `xdescribe` / `describe.skip` / `xit` / `it.skip` / `test.skip` / `fit` / `.only` — or every `describe` reached from changed code is so marked | HIGH |
| `coverage-commented-it` | touched spec file contains `// it(` / `// describe(` / `/* it(` block commenting out an active test for the changed symbol | MED |

† `route-added-or-renamed`: LOW = new + linked from nav · MED = renamed without redirect · HIGH = navigation targets unregistered path.

### Framework overlay (gated by `env.FRAMEWORK`)

- **angular**: standalone/NgModule mismatch=MED · `OnPush` missing where neighbors use it=LOW · `HttpClient` call without `HttpTestingController` assertion=HIGH · new route without `canActivate`/`canMatch` when neighbors have one=MED · NgRx action/reducer/effect without matching spec=HIGH · non-pure pipe safety=LOW.
- **react**: rules-of-hooks violation=HIGH · component mutating props=HIGH · class component in function-component repo=LOW · `setState` in `useEffect` without guard=MED · `memo`/`useMemo`/`useCallback` on cheap primitive=LOW · `Suspense` without `fallback`=MED · `forwardRef` dropping `ref`=MED · missing error boundary on new route when neighbors have one=MED.

---

## Phase 2 — Severity (internal only, never display)

`final = clamp(base + blast + coverage, LOW..HIGH)`, then ground-truth override.

- **Blast** from `coverage[file].callerCount`: ≤1=×1.0 · 2–5=×1.25 · 6–20=×1.5 · >20=×2.
- **Coverage adjust** from `coverage[file].coverageStatus` + `qualityNotes`:
  - `none` → +1 step.
  - `asserts` AND test covers changed branch → −1 step.
  - Any note mentioning `fit`/`.only`/`xit`/`xdescribe`/`describe.skip`/`test.only`/`it.skip`/`test.skip`/commented-out `it(`/`describe(` → **treat `coverageStatus` as `none`, NOT `asserts`**, and emit a `coverage-disabled-xdescribe` / `coverage-commented-it` finding in addition to the original classifier.
- **Override**: `checks.lint.status="fail"` on touched file OR `checks.unit.status="fail"` referencing changed symbol → force **HIGH**.

---

## Phase 3 — Fixes (WRITES CODE)

1. Record `FEATURE_BRANCH = git symbolic-ref --short HEAD`. If detached, emit one HIGH "HEAD detached — checkout a branch" and skip to step 8 of the pipeline.
2. Order: contract/type first → consumers → tests → cosmetic (LOW) last.
3. One fix per finding. Minimum change only.
4. Re-run skill 5 after edits. If a new error appears, `git checkout -- <file>` and downgrade finding to "fix attempted, reverted — manual" with the error log.
5. NEVER commit/stash/push/reset/clean/switch branches.

### Recipes

Pick the row matching `env.FRAMEWORK` (fall back to `FRAMEWORK_FAMILY`). Every recipe writes real code.

| Classifier | Fix |
|---|---|
| `subscribe-leak` | Angular: inject `DestroyRef` + `takeUntilDestroyed(this.destroyRef)` or `destroy$ Subject` + `takeUntil`. React: move into `useEffect` returning cleanup. |
| `effect-missing-deps` | Add missing ids to deps. If that loops, wrap with `useCallback`/`useMemo` or move inside effect. |
| `stale-closure-event-handler` | Ref-proxy (`handlerRef = useRef(h); useEffect(()=>{handlerRef.current=h;});`) OR add handler to effect deps. |
| `state-setter-in-render` | Move setter to `useEffect`/event/ref, or compute with `useMemo`. |
| `object-literal-context-value` | Hoist to `useMemo(() => ({…}), [deps])`; callbacks in `useCallback`. |
| `uncontrolled-to-controlled` | Init state with `''`; `value={data ?? ''}`. |
| `unsanitized-html-sink` | Angular: `DomSanitizer.bypassSecurityTrustHtml(DOMPurify.sanitize(v))`. React: `dangerouslySetInnerHTML={{__html: DOMPurify.sanitize(v)}}`. Add `dompurify` to deps if missing. |
| `timer-without-cleanup` | Angular: field id + `clearInterval/Timeout` in `ngOnDestroy`. React: `useEffect(() => { const id = setInterval(…); return () => clearInterval(id); }, […])`. |
| `storage-write-unstringified` | Wrap with `JSON.stringify`; reads `try { JSON.parse } catch { fallback }`. Use existing wrapper if neighbors do. |
| `a11y-interactive-element` | Prefer `<button type="button">`. Else `role="button"` + `tabindex="0"` + keydown (Angular `(keydown.enter)` `(keydown.space)`; React `onKeyDown` handling Enter/Space). |
| `form-submit-unvalidated` | Angular Reactive: `if (this.form.invalid) { this.form.markAllAsTouched(); return; }`. RHF: `handleSubmit(onValid,onInvalid)` or early-return on `!isValid`. Formik: gate on `isValid`. Zod/Yup: `safeParse` + early return. |
| `reactive-form-mismatch` | Angular: add/remove `FormControl` to match template. RHF: sync `register('x')` with schema. Formik: sync `initialValues` with `<Field name>`. |
| `hardcoded-user-copy` | Replace with neighbor i18n (`\|translate`, `i18n=`, `t('key')`, `<FormattedMessage>`). Add key to every locale JSON with English default. |
| `missing-key-map` | Angular: `trackBy: trackByFn` + declare. React: `key={item.id ?? idx}`. Prefer stable id. |
| `swallowed-catch` | Replace with neighbor error surface (Angular `catchError` + `MatSnackBar`/toast; React `useToast`/`sonner.toast.error`/context). Rethrow or set local `error`. |
| `target-blank-no-rel` | Append `rel="noopener noreferrer"`. |
| `console-or-debugger` | Delete. Do not replace with logger unless neighbors use one. |
| `unguarded-query-param` | `?? <default>` or zod/valibot `.catch(default)`/`.default(…)`. |
| `missing-http-error-branch` | Add neighbor-standard error branch bound to `error` state populated in HTTP error callback. |
| `endpoint-added` | Add runtime stub using `env.HTTP_MOCK_LIB`: MSW handler / Angular dev service / `cy.intercept` / axios-mock-adapter / nock. Mirror neighbor pattern. |
| `asset-path-added` | Grep basenames under `src/assets/**`, `public/**`, `static/**`, `cdn-content/**`, `assets/**`; rewrite to real path. If none found → proposed-only. |
| `route-added-or-renamed` (renamed) | Angular: `{ path:'<old>', redirectTo:'<new>', pathMatch:'full' }`. React Router v6+: `<Route path="<old>" element={<Navigate to="<new>" replace />} />`. |
| `broken-workspace-alias` | Update import to existing path OR add `paths` entry in `tsconfig`/`vite.config`/`webpack.config`. |
| `import-not-in-manifest` | Add to `dependencies` compatible with framework major. Do NOT install; prompt dev. |
| `abort-controller-missing` | React: `useEffect` + `AbortController` + `signal`, abort on cleanup. Angular RxJS: `switchMap` + `takeUntilDestroyed()`. |
| `await-in-loop` | `await Promise.all(xs.map(work))` when independent. `p-limit` for concurrency cap. |
| `floating-promise` | `await` / `void` / `.catch(e => showToast(e))`. If caller can't be async, try/catch IIFE. |
| `direct-state-mutation` | React: new ref — `setItems(prev => [...prev, item])`. NgRx/RTK: keep Immer `createSlice`; classic reducers return `{...state, …}`. |
| `double-submit-guard-missing` | Angular: `submitting=signal(false)` + template `[disabled]="submitting()"` + `finalize`. React: `[submitting,setSubmitting]` + `if(submitting)return` + try/finally. RHF: bind `disabled` to `formState.isSubmitting`. |
| `autofill-onchange-gap` | React: `onChange={e => setValue(e.target.value)}`. Angular template-driven: `[(ngModel)]`; reactive: `formControlName` not `[value]`. |
| `event-listener-no-remove` | Stable reference (field/`useCallback`); add+remove with same ref. Angular: `Renderer2.listen(…)` returns teardown fn. |
| `websocket-no-reconnect` | Factory with `onclose` → exp-backoff (cap 30s), `onerror` → toast, `ready` state. Teardown sets `closedByClient=true`. |
| `polling-no-stop` | Guard chain with `AbortController.signal.aborted` OR `timer(0,n).pipe(takeUntilDestroyed())`. |
| `hydration-nondeterminism` | Compute in `useEffect` (or Angular `afterNextRender`); stable placeholder on server. |
| `cookie-insecure-flags` | `"name="+encodeURIComponent(v)+"; Secure; SameSite=Strict; Path=/"`. Auth tokens → proposed-only (recommend server-set `HttpOnly`). |
| `image-missing-dimensions` | Explicit `width`+`height` = intrinsic size. Responsive: CSS `aspect-ratio`. |
| `image-missing-alt` | Descriptive `alt="…"` via neighbor i18n if used; `alt=""` only for decorative (comment why). |
| `html-unclosed-tag` | Close at correct depth. Never self-close non-void HTML elements. Lift structural directives to `<ng-container>`/fragment when conditional. |
| `html-invalid-nesting` | Replace outer element with valid container. Never silence with `display:contents`. |
| `html-duplicate-id` | Rename one + update every `for`/`aria-labelledby`/`getElementById`. Loops: `id="row-{{item.id}}"` / `` id={`row-${item.id}`} ``. |
| `global-listener-no-ondestroy` | Stable class-field handler; register in `ngOnInit`, remove in `ngOnDestroy`. Preferred: `Renderer2.listen` teardown or `fromEvent(…).pipe(takeUntilDestroyed())`. |
| `unsafe-date-parse` | `new Date(Date.UTC(y,m-1,d))` OR existing date lib (`dayjs`/`date-fns`/`luxon`). Never introduce a new one. |
| `debounce-missing` | Angular RxJS: `debounceTime(300), distinctUntilChanged()`. React: `useDeferredValue` or `useDebouncedCallback` (if `use-debounce` present), else local effect+timeout. |
| `circular-import-risk` | Extract shared symbols to 3rd module both import, or invert via DI/emitter. Fix the smaller file. |
| `env-var-no-fallback` | `?? <literal>` for non-secrets. Required values: one build-time assertion module imported from entry. |
| `file-upload-unvalidated` | Top-of-handler guard: `const MAX=5*1024*1024; const OK=['image/png','image/jpeg']; if(f.size>MAX)return; if(!OK.includes(f.type))return;`. Use neighbor toast. |
| `paste-unsanitized` | Accept only `text/plain`. If HTML required, `DOMPurify.sanitize(html,{ALLOWED_TAGS,ALLOWED_ATTR})`. |
| `optimistic-update-no-rollback` | Snapshot prev; restore in `.catch`. TanStack Query: `onMutate`/`onError`/`context` rollback. |
| `shared-mutable-export` | Factory `export const makeObj = () => ({…})` per consumer, OR Angular `providedIn:'root'` singleton with a reset API. |
| `regex-catastrophic-backtracking` | Rewrite with atomic classes/anchors; bound input with `.slice(0,MAX)`. |
| `rxjs-share-missing` | `.pipe(shareReplay({bufferSize:1,refCount:true}))` at service boundary. |
| `angular-zone-escape` | Wrap UI write in `ngZone.run(() => {…})`, or switch to Signals. |
| `micro-frontend-global-style` | Move to scoped stylesheet. Unavoidable globals: prefix with root-level app-id class. |

### Propose-only (no auto-fix)

- `endpoint-added` with no neighbor spec pattern to mirror.
- `asset-path-added` with no candidate file.
- `major-dep-bump` (needs human compatibility call).
- Any HIGH whose fix would exceed 15 lines across >2 files → include exact diff as proposed patch, mark 📝.

### Test-gap fixes

For every MED/HIGH where `coverageStatus === "none"`, write a minimal sibling spec using `env.TEST_RUNNER` + `env.COMPONENT_TEST_LIB`:

- Angular: Jest/Jasmine with `TestBed` (+ `@testing-library/angular` if present); `HttpTestingController` for HTTP; `<name>.spec.ts`.
- React: Vitest/Jest with `@testing-library/react`; MSW for HTTP if present; `<name>.test.tsx` (or neighbor convention).

Every generated spec: (1) imports the changed symbol by real name, (2) renders/invokes and makes a **behavioral** assertion — not snapshot, not TODO, not `it.skip`, (3) covers the specific changed branch, (4) uses `env.HTTP_MOCK_LIB` — never mix.

---

## Output

First line — `VERDICT: LOW_RISK|MEDIUM_RISK|HIGH_RISK` + optional ` (analysis-only)` and/or ` (fixes-applied)`.

Then in order:

1. **Detected Environment** — 3-row table: App name · Base ref · Feature branch.
2. **Findings table** — Rule ID · Severity · File:Line · Classifier · Coverage (✅ asserts / ⚠️ weak / ❌ none) · Fix (🛠 applied / 📝 proposed / ⚪ manual).
3. **Per-finding detail** (H→M→L). Each block: H3 `### 🔴 HIGH — QA-H01 — <title>` (icons 🔴🟡🟢); `**Where:**` path+lines; `**Evidence:**` fenced real-code excerpt; `**Why it is a bug:**` one sentence of end-user impact; `**Coverage:**` sibling spec path + quality note (or "none"); `**Fix applied:**` `diff` fence OR `(manual — see proposal)` + proposal diff for 📝; `**Post-fix checks:**` `PASS`/`FAIL: <tail>`.

**FORBIDDEN sections** — do NOT emit any of these in chat or in the written report (markdown or HTML):
- "Files Changed" / "Files Changed (diff scope)" / "Diff scope"
- "Classifier Signals" / "Signals" / "Classifier"
- "Verification" / "Verification Summary" / "Checks"

Diff-scope files, classifier labels, and verification outcomes are already encoded per-finding (via `**Where:**`, the Classifier column, and `**Post-fix checks:**`); do not duplicate them as standalone sections.

End with a **Report** line: served HTML URL + on-disk md/html paths from skill 8.

---

## Constraints

- Every finding quotes real diff code. No generic boilerplate.
- HIGH requires failing command output OR a diff excerpt proving the bug OR grep proving absent coverage — else downgrade to MED.
- Never edit outside `env.WORKSPACE_ROOT` or inside `env.IGNORE_GLOBS`.
- Never install deps. If a fix needs one, edit `package.json` only.
- No dev-server/live-e2e/screenshots.
- Repo paths in report output are plain text (optionally `:L42`). External `http(s)://` links remain links.

## Rule IDs

`QA-<SEV><NN>` where SEV ∈ {H,M,L}, NN sequential within severity for this run. Local to run — no registry.
