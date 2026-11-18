# Skill: coverage-locator

For a given source file, locate its sibling unit spec, component spec, e2e specs, caller count (blast radius), and quality notes about the existing spec.

## Inputs

- `sourcePath` — workspace-relative path to a changed source file.
- `exportedSymbols` — array of symbol names the orchestrator extracted from the diff (functions, classes, components, hooks).
- `env` — from `detect-environment` (`TEST_RUNNER`, `COMPONENT_TEST_LIB`, `HTTP_MOCK_LIB`, `FRAMEWORK`).

## Outputs

A `coverage` object:

- `siblingSpec` — path to a sibling unit/component spec, or `null`.
- `siblingSpecAssertsSymbol` — boolean; `true` iff at least one assertion references a name in `exportedSymbols`.
- `e2eSpecs` — array of paths under Cypress / Playwright / WebdriverIO / Nightwatch conventional dirs that reference the feature folder or the source file's route.
- `storySpec` — path to a `*.stories.*` / `*.cy.*` component-test file, or `null`.
- `callerCount` — integer; count of non-test files importing `sourcePath` or any of its `exportedSymbols`.
- `qualityNotes` — array of strings; each is one of the checks in the Quality block below.
- `coverageStatus` ∈ {`asserts`, `weak`, `none`}.

## Procedure

### 1. Locate sibling spec

Search candidates, first match wins:

1. Same directory: `<basename>.spec.{ts,tsx,js,jsx,mjs,cjs}` or `<basename>.test.*`.
2. `__tests__/<basename>.{spec,test}.*` adjacent to the source.
3. Mirror tree: `tests/unit/<rel-path>.{spec,test}.*`, `test/<rel-path>.{spec,test}.*`.

### 2. Locate story / component spec

- `<basename>.stories.{ts,tsx,mdx}` — CSF.
- `<basename>.cy.{ts,tsx}` — Cypress component testing.
- `<basename>.browser.test.*` — vitest browser mode.
- Any testing-library file anywhere in the repo that imports the source by path — captured only if the repo uses `@testing-library/*`.

### 3. Locate e2e specs

- Cypress: `cypress/e2e/**`, `cypress/component/**`.
- Playwright: respect `playwright.config.*` `testDir`; default `playwright/**` and `tests/**`.
- WebdriverIO: `test/specs/**`.
- Nightwatch: `tests/**`.

Match by: (a) feature-folder name present in both source path and e2e path, or (b) the route path the changed file owns (if resolvable from a router config).

### 4. Caller count (blast radius)

- For each symbol in `exportedSymbols`: `grep` the repo for imports of `sourcePath` or named imports of that symbol.
- Exclude any path under a spec/test directory.
- `callerCount` = unique file count across all matches.

### 5. Quality checks

Apply every check that matches the detected `TEST_RUNNER` / libs. Append a short string to `qualityNotes` for each trigger.

- **No assertion references any symbol in `exportedSymbols`** → "spec exists but does not exercise new symbol".
- **Contains `xit` / `xdescribe` / `.only` / `fdescribe` / `fit` / `it.skip` / `describe.skip` / `test.only`** → "focused/skipped tests committed".
- **Angular + `HttpTestingController` without `verify()`** → "HttpTestingController.verify() missing".
- **MSW + no reachable `server.resetHandlers()` / `server.close()` in teardown** → "MSW teardown missing".
- **React Testing Library + only `container.querySelector` assertions, no `screen.*`** → "tests implementation, not behavior".
- **`>5` `jest.fn()` / `vi.fn()` / `*.spyOn(` calls AND zero `toHaveBeenCalled*` / `toEqual` / `toMatchObject` assertions** → "weak mocks".
- **Snapshot-only file (no `expect` beyond `toMatchSnapshot`)** → "snapshot-only coverage".

### 6. Derive coverageStatus

- `none` — (takes precedence over `asserts`/`weak`) no `siblingSpec` AND no `storySpec` AND no `e2eSpecs`, OR a sibling spec exists but every top-level `describe`/`it` reached from the changed symbol is `xdescribe` / `describe.skip` / `xit` / `it.skip` / `test.skip` / commented-out. In this case the `qualityNotes` MUST include `"focused/skipped tests committed — no runnable assertions"` and `siblingSpecAssertsSymbol` MUST be set to `false` even when assertion text is present, because the assertions do not execute.
- `asserts` — sibling spec exists AND `siblingSpecAssertsSymbol == true` AND `qualityNotes` is empty.
- `weak` — sibling spec exists but one or more non-disabling quality notes fired, OR `siblingSpecAssertsSymbol == false` for reasons other than disabled suites.

## Notes

- This skill is read-only.
- It MUST NOT execute the tests. Use `scoped-lint-and-test` for execution.
- The orchestrator uses `coverageStatus` and `callerCount` to adjust severity per the agent's severity model.
