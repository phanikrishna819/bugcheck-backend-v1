# Frontend Bug Check — backend

A Python (FastAPI) backend that takes an uploaded Angular or React app, runs
a hybrid **static + AI-assisted** analysis, and returns a bug report with
severities and suggested fixes. Built by adapting six `bugcheck` agent skill
files that were originally written for a different kind of agent — see
["What changed from the original skill files"](#what-changed-from-the-original-skill-files)
below.

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste a free key from https://aistudio.google.com/apikey
uvicorn app.main:app --reload
```

Then:

```bash
curl -F "file=@my-angular-app.zip" http://localhost:8000/api/analyze
```

Zip your app folder (`package.json` at the root or one level down) and POST
it to `/api/analyze`. You'll get back JSON with a verdict, a findings list,
and a run ID; `GET /api/runs/{run_id}/report.html` gives you the same thing
as a readable page.

No `GEMINI_API_KEY`? The service still runs — it just skips the AI-assisted
pass and returns static/deterministic findings only, with a note saying so.

## Your three questions

**Does this need an LLM call at all?**
Partly. Roughly half of the original skill's bug classifiers are literal
patterns — `console.log` left in code, `target="_blank"` missing `rel`,
localStorage writes that skip `JSON.stringify`, unclosed HTML tags, missing
`alt` text, asset paths that don't exist on disk. Those run as plain Python
regex/HTML-parser checks in `app/classifiers/`, **with no LLM call, no cost,
no rate limit, and no risk of a hallucinated finding.** The rest of the
classifier list — missing `useEffect` deps, unvalidated form submits,
un-rolled-back optimistic updates, stale closures — genuinely require
judgment about what the code *means*, not just what it matches. That's the
part that goes to Gemini, one call per selected file (see
`app/llm/analyzer.py`), and it also writes the human-readable "why this
matters" + suggested-fix text for the static findings, since a regex can
match a pattern but can't explain it. This split is why the report tags
every finding as "✅ deterministic check" or "🤖 AI-reviewed" — it's an
honest signal of how much to trust each one.

**Which free model?**
`gemini-2.5-flash`, set as the default in `.env.example`. As of the Gemini
Developer API's current pricing page, free tier now covers only the Flash /
Flash-Lite families (Pro was moved behind billing on April 1, 2026) — free
options include `gemini-2.5-flash`, `gemini-2.5-flash-lite`,
`gemini-3.5-flash`, and `gemini-3.5-flash-lite`. I picked `2.5-flash`
because it's the most battle-tested free GA model with a 1M-token context
(useful for large files) at a reasonable RPM. Swap to
`gemini-2.5-flash-lite` if you want more throughput and don't mind slightly
shallower reasoning, or `gemini-3.5-flash` for stronger reasoning at the
same $0 (newer, less proven). **Two things worth knowing before you point
this at real code:** free-tier rate limits are small (single digits to
~15 requests/minute depending on model — check
[ai.google.dev/gemini-api/docs/rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits)
for the current number) — that's why there's a per-run file cap, below —
and Google's pricing page states free-tier content **is used to improve
their products**, unlike the paid tier. For a demo/personal-project app
that's a non-issue; for actual production/proprietary code, either use a
paid API key or budget for that before uploading real repos.

**Do you need memory/storage, and what kind?**
For this MVP: yes, but only a little — `app/db.py` is plain SQLite (no
ORM) tracking run history (verdict, counts, links to the report files) so
runs are listable and reports are re-fetchable. That's genuinely all a
single-upload, single-report tool needs. See the roadmap below for when to
outgrow it.

## Why there's a file cap

The original skill only ever looked at a git **diff** — the files changed
in one branch/PR. That's what keeps an LLM-per-file design affordable: a
typical PR touches a handful of files. This MVP's "beginner: upload the
whole app" flow doesn't have that luxury — a real app can have hundreds of
scannable files, and free-tier RPM can't cover an LLM call per file at that
scale. `MAX_FILES_FOR_LLM` (default 40) caps the AI-assisted pass;
`app/pipeline.py`'s `_select_files_for_llm` prioritizes files that already
have static findings, then the largest remaining files. Static/deterministic
checks still run on **every** file regardless of the cap — only the
LLM-enrichment step is capped. Raise the cap if you're on a paid key, or
better: implement diff-mode (next section) once GitHub-repo-link support
exists, since "only changed files" both matches how the original skill was
designed and sidesteps the whole problem.

## Roadmap / extension points (each one is a stub or a documented gap in the code)

- **GitHub repo + branch link, diff-only scope** — `app/scope/git_diff.py`
  is a stub with porting notes for `diff-scope-resolver.md`. This is the
  highest-value next step: it fixes the file-cap problem above *and* is
  the input mode you said you want next.
- **Coverage-awareness / blast-radius severity** (`coverage-locator.md`'s
  job) — not implemented; needs a real import graph over the uploaded app
  to compute caller counts. Worth adding once repo-scale analysis exists.
- **Running the app's own lint/tests** (`scoped-lint-and-test.md`'s job) —
  skipped, because an uploaded zip essentially never includes
  `node_modules`, and the original skill explicitly forbids running an
  install. This only becomes viable with a sandboxed execution environment
  you trust to `npm ci` arbitrary uploaded code in.
- **Auto-applying fixes** (`bugcheck_agent.md` Phase 3) — deliberately not
  ported. That phase writes code, re-runs tests, and does
  `git checkout -- <file>` to revert a fix that broke something — none of
  which is safe without a real git working tree and a sandboxed test run.
  Suggested fixes are text/snippets for a human to apply.
- **Async processing** — `/api/analyze` currently blocks until the whole
  pipeline finishes, which is fine for a curl/demo flow but won't be once
  there's an interactive UI. Swap to a background task (FastAPI
  `BackgroundTasks`, or Celery/RQ once you need retries and horizontal
  scaling) plus a `/api/runs/{id}/status` endpoint for polling.

## Memory / storage roadmap

| Stage | What | Why |
|---|---|---|
| **Now** | SQLite (`app/db.py`) + local filesystem for reports/uploads | Zero ops, enough for single-user run history |
| **Interactive UI, multi-user** | Postgres instead of SQLite; object storage (S3/GCS-compatible) instead of local disk for uploads + reports | Concurrent writers, durability, and reports need to survive a redeploy |
| **GitHub-repo-scale analysis** | A vector store (Chroma for local dev, pgvector/Qdrant in production) over embedded file chunks | Once repos are too big to paste whole files into a Gemini prompt, you retrieve the relevant chunks instead — this is also what would power a "chat about this finding" feature grounded in the actual codebase |
| **Blocking-work-at-scale** | A task queue (Celery/RQ/Arq) + Redis | Decouples the HTTP request from a run that might take minutes, and lets the future UI show live progress |

Don't build the vector store or Postgres now — nothing in the current
scope needs them yet, and premature infra is its own maintenance cost.

## What changed from the original skill files

| Skill | What happened to it |
|---|---|
| `bugcheck_agent.md` (orchestrator) | Its classifier table → `app/classifiers/rules.py` (data, shared by static + LLM). Its severity model → `app/report/severity.py` (simplified: base severity only, no blast-radius/coverage adjustment yet). Its report structure/forbidden-sections rule → `app/report/renderer.py`. Its Phase 3 (auto-fix + git revert loop) → **not ported**, see roadmap above. |
| `detect-environment.md` | Ported closely in `app/environment/detect.py` — same framework-resolution order, same lockfile sniffing, same `IGNORE_GLOBS`/`LANG_EXTS`. Git-specific steps (root via `git rev-parse`, `git fetch`) dropped — there's no git repo, just an extracted zip. |
| `diff-scope-resolver.md` | Not used yet — this MVP scans the whole upload (`app/scope/full_app.py`) instead of a diff. Its logic is the porting target for `app/scope/git_diff.py` once GitHub-repo-link input exists. |
| `coverage-locator.md` | Not implemented. Needs a real import graph over the uploaded app; noted as a gap, not silently dropped. |
| `scoped-lint-and-test.md` | Not implemented. The precondition it names itself ("skip if `node_modules` missing, never install") would fire on almost every upload anyway. |
| `report-renderer.md` | Section structure and "forbidden sections" rule kept in `app/report/renderer.py`. The local-HTTP-server + "open in Simple Browser" delivery mechanism dropped — that's specific to an IDE-agent tool call this backend doesn't have; reports are just written to disk and served via `/api/runs/{id}/report.html`. |

## Project layout

```
app/
  main.py                 FastAPI app: /api/analyze, /api/runs, report file serving
  pipeline.py              orchestrates detect -> scope -> static scan -> LLM pass -> report
  config.py                env-driven settings
  db.py                    SQLite run history
  environment/detect.py     framework/tooling detection
  scope/                    which files get analyzed (full_app now, git_diff later)
  classifiers/
    rules.py                 the shared classifier taxonomy (static + llm)
    static_scan.py            regex engine
    html_checks.py            HTMLParser-based structural checks
  llm/
    gemini_client.py          rate-limited Gemini wrapper
    analyzer.py                per-file prompt building + response parsing
  report/
    schema.py                  Finding / Report pydantic models
    severity.py                 verdict + rule-id assignment
    renderer.py                  markdown + HTML report writer
  uploads/handler.py          safe zip extraction (zip-slip guarded, size-capped)
```

## Known limitations (MVP, by design)

- JSX/TSX templates aren't parsed as a tree — the HTML structural checks
  (`html-unclosed-tag`, `image-missing-alt`, etc.) only run against literal
  `.html` files today. A `<img>` missing `alt` inside a `.jsx` file won't
  be caught until that gets a JSX-aware pass (regex over JSX attributes, or
  a real parser like `esprima`/`@babel/parser` via a Node subprocess).
- `event-listener-no-remove` and `timer-without-cleanup` are whole-file
  call-count heuristics, not real data-flow analysis — they're flagged
  `confidence: low` in the report on purpose.
- CSS analysis is minimal (one LLM-only rule for unscoped globals); the
  original taxonomy didn't have many CSS-specific classifiers to begin
  with, so this mirrors that rather than under-implementing something that
  was there.

---

# Chat agent API (Python port of the Java backend)

The service now also implements the **chat/tool agent** that the deployed
React UI (`bugcheck-agent-chatbot/frontend`) speaks. The production build of
that UI is committed under `app/static` and served by this same service, so
UI and API share one origin (and one Render free-tier instance).

## Architecture

```
Browser -> FastAPI (this repo)
             |-> /            bundled React UI (app/static)
             |-> /api/*        chat/tool agent + zip scan pipeline
             |-> workspace tools (files/git/shell/patch)
             |-> SQLite (sessions, messages, workspaces, runs)
             |-> LLM provider (OpenAI or Gemini)
```

Request flow for a chat turn:

1. `POST /api/chat/sessions/{id}/messages` stores the user turn.
2. `app/agent/service.py` builds the prompt: `bugcheck.agent.md` + every
   `skills/*.md` (from `app/assets`, or `AGENT_ASSETS_DIR`) + session state +
   the stored transcript.
3. The model answers, or requests tools. Tool calls run in
   `app/tools/registry.py`, their output is appended as `role=tool`, and the
   model is called again — up to `AGENT_MAX_TOOL_ROUNDS` (default 8).
4. The whole transcript is persisted, so follow-up messages keep the code
   context instead of losing it between turns.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness + which LLM providers/models are active |
| GET | `/api/skills` | `{assetsRoot, skills[]}` for the UI sidebar |
| POST | `/api/workspaces` | `{path}` -> bind local dir or clone git URL |
| POST | `/api/chat/sessions` | `{workspaceRoot?, allowEdits}` -> session |
| GET | `/api/chat/sessions` | list sessions |
| GET | `/api/chat/sessions/{id}` | one session |
| DELETE | `/api/chat/sessions/{id}` | delete session |
| POST | `/api/chat/sessions/{id}/messages` | send a turn, returns the session |
| POST | `/api/chat/sessions/{id}/report.pdf` | scan the session workspace, download the fix PDF |
| POST | `/api/analyze` | zip upload scan (existing pipeline) |
| GET | `/api/runs`, `/api/runs/{id}`, `.../report.md`, `.../report.html` | scan history |

## Provider routing

`LLM_PROVIDER=auto` (default) picks per purpose and falls back to the other
provider when both keys exist:

| Purpose | First choice | Fallback |
| --- | --- | --- |
| `chat` (tool loop) | OpenAI (`gpt-4.1-mini`) | Gemini via its OpenAI-compatible endpoint |
| `scan` (per-file JSON) | Gemini (free tier + RPM throttle) | OpenAI JSON mode |

Override with `LLM_PROVIDER`, `LLM_CHAT_PROVIDER`, `LLM_SCAN_PROVIDER`,
`LLM_CHAT_MODEL`, `LLM_SCAN_MODEL`. No key set -> static-only scan and a
clean `502` on chat.

## Workspaces

- **Local path** (`C:\...`, `/home/...`) — works when the backend runs on the
  same machine; identical to the Java behavior.
- **Git URL** (`https://github.com/org/repo[.git]`, `git@...`) — shallow
  cloned into `WORKSPACE_DIR` and analyzed there, which is what makes the
  cloud deployment useful.

Set `WORKSPACE_MODE=local|clone|both`.

## Safety model

- Every path goes through `resolve_inside`, which rejects anything outside the
  workspace root (symlinks are resolved).
- `apply_patch`/`write_report` require `allowEdits`; `.git` is off limits.
- `apply_patch` refuses ambiguous matches (the Java version replaced *every*
  occurrence) and writes a `.bak` before editing.
- `run_command` uses an **allowlist** (`AGENT_ALLOWED_COMMANDS`) plus a
  denylist for git-writing/destructive commands; set `AGENT_ALLOW_SHELL=false`
  in production to remove it entirely.
- Child processes are drained by a reader thread and killed at the timeout, so
  large `git diff` output no longer deadlocks.
- Sessions expire after `SESSION_TTL_MINUTES` (default 12h).

## Run locally

```powershell
cd C:\Users\phani\OneDrive\Desktop\MTech\Agent\bugcheck-backend\bugcheck-backend
.\\venv\\Scripts\\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env    # then fill OPENAI_API_KEY and/or GEMINI_API_KEY
.\\venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8088
```

Point the UI at it in dev with `VITE_API_BASE_URL=http://localhost:8088` (or
keep the Vite proxy).

## Deploy (Render)

`render.yaml` + `Dockerfile` are included: a single service
(`bugcheck-agent-api`, health check `/api/health`, `AGENT_ALLOW_SHELL=false`)
that serves both the UI and the API. No nginx/proxy service is needed, which
also removes the 502s that happen when a separate proxy service wakes before
the API.

To refresh the bundled UI, rebuild it in the frontend repo and copy
`frontend/dist/*` into `app/static/`, then redeploy. Render's free plan has an
ephemeral disk: sessions, clones, and reports reset on redeploy / 15-minute
idle spin-down unless a persistent disk is attached.

## Tests

```powershell
.\\venv\\Scripts\\python.exe -m pytest tests -q
```

Covers the UI contract, session persistence, workspace escape rejection,
ambiguous-patch handling, the command allowlist, and the read tools.

