# Skill: detect-environment

Resolve the runtime environment of the current workspace by reading the repo. Never hardcode — everything comes from lockfiles, `package.json`, and on-disk config.

## Inputs

- None (operates on the current workspace).

## Outputs

A single `env` object with these fields:

- `WORKSPACE_ROOT` — absolute path from `git rev-parse --show-toplevel`.
- `PKG_MGR` ∈ {`pnpm`, `bun`, `yarn`, `npm`}.
- `FRAMEWORK` ∈ {`angular`, `react`, `unsupported`}.
- `FRAMEWORK_FAMILY` ∈ {`angular`, `react`, `other`}. Callers MUST stop when this is `other` (emit one LOW finding `unsupported framework: <name>` and skip to reporting).
- `LANG_EXTS` — fixed array `[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"]`.
- `LINT_CMD` — string, scoped command template (files appended at call site).
- `UNIT_CMD` — string, base command (related-tests flag appended at call site).
- `TEST_RUNNER` ∈ {`jest`, `vitest`, `jasmine-karma`, `mocha`}.
- `COMPONENT_TEST_LIB` ∈ {`@testing-library/react`, `@testing-library/angular`, `angular-testbed`, `none`}.
- `HTTP_MOCK_LIB` ∈ {`msw`, `nock`, `axios-mock-adapter`, `HttpTestingController`, `cy.intercept`, `none`}.
- `DEFAULT_BASE` — `origin/main` if present, else `origin/master`.
- `IGNORE_GLOBS` — array of glob patterns to skip.

## Procedure

1. **Workspace root** — `git rev-parse --show-toplevel`.

2. **Package manager** — check lockfiles in order:
   - `pnpm-lock.yaml` → `pnpm`
   - `bun.lockb` → `bun`
   - `yarn.lock` → `yarn`
   - else → `npm`

3. **Framework** — inspect `package.json` `dependencies` + `devDependencies`. Resolve in this order:
   1. `@angular/core` → `angular` (note SSR if `@angular/ssr` or `@angular/platform-server` present).
   2. `react` AND none of `next`, `@remix-run/react`, `@remix-run/node`, `gatsby`, `react-scripts` are present → `react` (note bundler: `vite`, `webpack`, `rspack`, `parcel`, `esbuild`).
   3. Any of `next` / `@remix-run/*` / `gatsby` / `react-scripts` present → `unsupported` (this agent rejects meta-frameworks; use plain React or Angular only).
   4. else → `unsupported`.

4. **Framework family** — `angular` → `angular`; `react` → `react`; else → `other`.

5. **Lang exts** — fixed `[.ts, .tsx, .js, .jsx, .mjs, .cjs, .mts, .cts]`.

6. **Lint cmd** — `${PKG_MGR} run lint` if `scripts.lint` exists in `package.json`, else `npx eslint`. Always scope to the changed-files list at the call site.

7. **Unit cmd** — first present wins:
   - `scripts.test` if defined.
   - `scripts["test-ci"]` if defined.
   - else `npx vitest run` if `vitest` is a dep.
   - else `npx jest`.
   - For Angular prefer the repo `scripts.test` (karma/jest) — never invoke `ng test` directly unless the script is absent.

8. **Test runner** — derive from `UNIT_CMD`:
   - mentions `vitest` → `vitest`.
   - mentions `jest` → `jest`.
   - Angular with karma config → `jasmine-karma`.
   - mentions `mocha` → `mocha`.

9. **Component test lib** — grep `devDependencies` for `@testing-library/angular` or `@testing-library/react`. If absent fall back to Angular `TestBed` for Angular repos, `none` otherwise.

10. **HTTP mock lib** — detect in this order: `msw`, `nock`, `axios-mock-adapter`, Angular `HttpTestingController` (if Angular), `cy.intercept` (if `cypress` is a dep). First match wins. If none → `none`.

11. **Default base** — `git fetch origin main master 2>/dev/null || true`, then pick `origin/main` if it resolves, else `origin/master`.

12. **Ignore globs** — fixed list: `.gitignore`, `dist/**`, `build/**`, `.next/**`, `out/**`, `storybook-static/**`, `coverage/**`, `node_modules/**`, `**/__generated__/**`, `**/*.min.*`, `*.lock`, `*.snap`.

## Notes

- This skill is pure detection. It MUST NOT run `npm install`, write files, or fetch anything other than the single `git fetch` in step 11.
- Callers should treat the output as immutable for the remainder of the run.
