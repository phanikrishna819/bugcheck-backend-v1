# Skill: scoped-lint-and-test

Run lint and unit tests **scoped to the changed files only**, using the detected runner's related-tests flag. Never run the full suite. Never install deps.

## Inputs

- `env` — from `detect-environment` (`LINT_CMD`, `UNIT_CMD`, `TEST_RUNNER`, `LANG_EXTS`, `PKG_MGR`).
- `changedFiles` — from `diff-scope-resolver`.

## Outputs

A `checks` object:

- `lint` — `{ ran: boolean, status: "pass" | "fail" | "skipped", log: string, files: string[] }`.
- `unit` — `{ ran: boolean, status: "pass" | "fail" | "skipped", log: string, command: string }`.
- `typecheck` — `{ ran: boolean, status: "pass" | "fail" | "skipped", log: string }`.
- `blocking` — `true` iff any of the above are `fail` OR if `node_modules` is missing (the orchestrator then emits a single HIGH "automated checks could not run" and proceeds in analysis-only mode).

## Procedure

1. **Pre-flight** — if `node_modules` is missing at `WORKSPACE_ROOT`, set every check to `skipped`, `blocking = true`, return immediately. Do NOT run any package-manager install.

2. **Filter lintable files**:
   - `lintables = changedFiles` ∩ `env.LANG_EXTS`.

3. **Lint** (parallel with unit):
   - If `lintables` is empty → `lint.ran = false, status = "skipped"`.
   - Else → run `${env.LINT_CMD} <lintables joined by space>` in the background, piping stdout+stderr to a tmp log. Record the command in `lint.files`.

4. **Unit tests** — choose the flag by `TEST_RUNNER`:
   - `jest` → `${env.UNIT_CMD} --findRelatedTests <changedFiles> --maxWorkers=50% --passWithNoTests`.
   - `vitest` → `${env.UNIT_CMD} --related <changedFiles> --changed=false --reporter=default`. If the repo's `scripts.test` does not forward `--related`, fall back to resolving the sibling spec paths via `coverage-locator` and running `${env.UNIT_CMD} --run <specPaths>`.
   - `jasmine-karma` (Angular classic) → run `scripts.test` as-is; set `CHROME_BIN` env var if an installed Chromium path is detectable; do NOT invent a file-scoping flag.
   - `mocha` → resolve sibling specs via `coverage-locator`, run `${env.UNIT_CMD} <specPaths>`.
   - Never run the full suite.

5. **Wait for both** — block until lint and unit complete. Record exit code → `status`.

6. **Type-check** (conditional):
   - Only run when the diff touches `.ts` / `.tsx` AND `package.json` has `scripts["type-check"]` or `scripts.typecheck`.
   - Command: `tsc --noEmit -p <nearest tsconfig>` scoped to the nearest `tsconfig.json` above the changed files.
   - Otherwise → `typecheck.ran = false, status = "skipped"`.

7. **Tail logs** — truncate each log to the last 4 KB for inclusion in the orchestrator's "Post-fix checks" block.

## Notes

- Lint and unit dispatch **in parallel**. Do not serialize them.
- This skill never swallows failures. A non-zero exit code becomes `status = "fail"` and the log is preserved.
- The orchestrator decides what to do with `blocking = true` (typically: emit a single HIGH and mark the run `(analysis-only)`).
