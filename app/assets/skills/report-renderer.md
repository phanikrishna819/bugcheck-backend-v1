# Skill: report-renderer

Render a findings payload into a timestamped markdown + HTML artifact pair under `.github/.audit-trails/`, serve it on a repo-scoped port, and open it in Simple Browser.

## Inputs

- `env.WORKSPACE_ROOT` — from `detect-environment`.
- `report` — object with:
  - `verdict` ∈ {`LOW_RISK`, `MEDIUM_RISK`, `HIGH_RISK`}, plus optional suffix `(analysis-only)` / `(fixes-applied)`.
  - `detectedEnvironment` — the 3-row table (App name / Base ref / Feature branch) already formatted as markdown by the orchestrator.
  - `featureBranch` — string, the branch fixes were applied to.
  - `findingsTable` — markdown table (Rule ID · Severity · File:Line · Classifier · Coverage · Fix Status).
  - `findingsDetail` — ordered array of markdown blocks (one per finding, High → Medium → Low).
- `mode` ∈ {`chat-only`, `with-html`}. The `Testing.portable` orchestrator always passes `with-html`; `chat-only` is reserved for other callers.

## Outputs

- `mdPath` — absolute path to the written markdown report, or `null` when `mode = chat-only`.
- `htmlPath` — absolute path to the written HTML report, or `null` when `mode = chat-only`.
- `url` — `http://localhost:<port>/<htmlBasename>`, or `null`.

## Procedure

### chat-only mode

1. Return `{ mdPath: null, htmlPath: null, url: null }`. The orchestrator emits chat output only.

### with-html mode

1. **Resolve report dir** — `REPORT_DIR = ${env.WORKSPACE_ROOT}/.github/.audit-trails`. Create it if missing.

2. **Timestamp** — `ts = YYYYMMDD-HHMMSS` in UTC.

3. **Write markdown** — `${REPORT_DIR}/bug-risk-report-<ts>.md` with this structure, in order:
   1. H1 `# Bug Risk Report — <ts> UTC`.
   2. Line `**Verdict:** <verdict>`.
   3. `## Detected Environment` followed by `report.detectedEnvironment` (exactly the 3 columns App name / Base ref / Feature branch — no other columns).
   4. Line `**Current branch:** <featureBranch>`.
   5. `## Findings` followed by `report.findingsTable`. The table MUST NOT contain a "Severity derivation" column.
   6. `## Findings Detail` followed by each entry of `report.findingsDetail` verbatim.
   7. Do NOT append a "Developer Hand-Off", "Next steps", "Files Changed" (or "Diff scope"), "Classifier Signals" (or "Signals"), "Verification" (or "Verification Summary" / "Checks"), or any other closing section.

4. **Render HTML** — invoke `node ${env.WORKSPACE_ROOT}/.github/agents/render-report.mjs <mdPath> <htmlPath>`. If that script is missing, self-provision a minimal one that reads markdown and emits standalone HTML via a bundled markdown renderer (no network).

5. **Serve** — compute `port` by hashing `WORKSPACE_ROOT` into the range `5500..5589`:
   - `port = 5500 + (fnv1a(WORKSPACE_ROOT) % 90)`.
   - If the port is in use, increment by 1 and retry up to 10 times.
   - Start `python3 -m http.server <port> --bind 0.0.0.0` with cwd `REPORT_DIR` in the background.
   - Poll `curl -fsS http://localhost:<port>/<htmlBasename>` until it returns 200 or 5 attempts elapse.

6. **Open** — call the Simple Browser open action with the URL from step 5.

7. **Return** — `{ mdPath, htmlPath, url }`.

## Notes

- The rendered report MUST mirror the chat output exactly; this skill does no reformatting beyond wrapping in the H1/H2 structure above.
- Never overwrite an existing timestamped report — the timestamp guarantees uniqueness; if a collision occurs (sub-second re-run), append `-2`, `-3`, etc.
- Never commit or add to `.gitignore` — `.github/.audit-trails/` is a working artifact directory managed by the repo owner.
