# Skill: diff-scope-resolver

Resolve the diff scope (base, head, merge-base, changed files) from a user-supplied branch reference or from the current working tree.

## Inputs

- `branchRef` (optional) — one of:
  - an Azure DevOps branch URL containing `?version=GB<branch>` (URL-encoded `%2F` allowed).
  - a GitHub branch URL of the form `…/tree/<branch>`.
  - a plain branch name.
  - null/empty → use current `HEAD`.
- `env.DEFAULT_BASE` — from `detect-environment`.
- `env.IGNORE_GLOBS` — from `detect-environment`.

## Outputs

A single `diff` object:

- `base` — resolved base ref (e.g. `origin/main`).
- `head` — resolved head ref (branch name or `HEAD`).
- `mergeBase` — commit SHA from `git merge-base`.
- `changedFiles` — array of workspace-relative paths (filtered by `IGNORE_GLOBS`).
- `includesWorkingTree` — boolean; `true` when `head == HEAD` and `git status --short` returned entries.

## Procedure

1. **Parse branch ref**:
   - If it matches `/[?&]version=GB([^&]+)/` → URL-decode capture group, use as branch.
   - Else if it matches `/\/tree\/([^/?#]+)/` → use capture group.
   - Else if non-empty → use as-is.
   - Else → `head = HEAD`.

2. **Fetch the branch if remote-only**:
   - If `head != HEAD` and `git rev-parse --verify refs/remotes/origin/<head>` fails, run `git fetch origin <head>:refs/remotes/origin/<head>`.

3. **Resolve merge-base**:
   - `mergeBase = git merge-base <env.DEFAULT_BASE> <head>`.

4. **Collect changed files**:
   - Committed: `git diff --name-only <mergeBase>..<head>`.
   - Working-tree (only when `head == HEAD`): `git status --short | awk '{print $2}'` — union with committed list, de-duplicate.

5. **Filter**:
   - Drop any path matching `env.IGNORE_GLOBS`.
   - Drop any path that no longer exists on disk AND is not in `--diff-filter=D` output (avoid noise on deletion-only diffs).

6. **Populate `includesWorkingTree`**:
   - `true` iff `head == HEAD` and the working-tree step produced at least one entry.

## Notes

- This skill is read-only except for the single `git fetch` in step 2.
- It MUST NOT check out, reset, stash, or rebase.
- Detached HEAD is allowed for reporting scope, but the orchestrating agent is responsible for refusing to write fixes in that state.
