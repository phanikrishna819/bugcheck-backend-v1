"""
Adapted from skills/detect-environment.md.

Kept as-is: the framework-resolution order (Angular -> plain React ->
meta-framework rejection -> unsupported), the lockfile-based package-manager
sniff, and the fixed LANG_EXTS/IGNORE_GLOBS lists.

Dropped / changed:
  - Steps 1 and 11 (`git rev-parse`, `git fetch origin main master`) assumed
    a live git checkout. An uploaded zip usually has no .git dir at all, so
    WORKSPACE_ROOT is just the extraction directory and DEFAULT_BASE/git
    fields are omitted. If the upload *does* contain a .git dir (e.g. the
    user zipped a clone), diff-mode in app/scope/git_diff.py can use it later.
  - Steps 6/7/8 (lint/unit commands, test runner) are detected here because
    they're cheap and useful for the report's "Detected Environment" table,
    but nothing in this MVP actually invokes them — see scoped-lint-and-test
    notes in README for why.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.file_walk import IGNORE_GLOBS, LANG_EXTS

META_FRAMEWORK_DEPS = {"next", "@remix-run/react", "@remix-run/node", "gatsby", "react-scripts"}


@dataclass
class Environment:
    workspace_root: str
    pkg_mgr: str = "npm"
    framework: str = "unsupported"          # angular | react | unsupported
    framework_family: str = "other"          # angular | react | other
    bundler: Optional[str] = None
    ssr: bool = False
    lang_exts: list = field(default_factory=lambda: list(LANG_EXTS))
    lint_cmd: Optional[str] = None
    unit_cmd: Optional[str] = None
    test_runner: Optional[str] = None
    component_test_lib: str = "none"
    http_mock_lib: str = "none"
    app_name: Optional[str] = None
    ignore_globs: list = field(default_factory=lambda: list(IGNORE_GLOBS))
    node_modules_present: bool = False


def _read_package_json(root: Path) -> dict:
    pkg_path = root / "package.json"
    if not pkg_path.exists():
        return {}
    try:
        return json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {}


def detect_environment(root: Path) -> Environment:
    env = Environment(workspace_root=str(root))

    # --- package manager (step 2) ---
    if (root / "pnpm-lock.yaml").exists():
        env.pkg_mgr = "pnpm"
    elif (root / "bun.lockb").exists():
        env.pkg_mgr = "bun"
    elif (root / "yarn.lock").exists():
        env.pkg_mgr = "yarn"
    else:
        env.pkg_mgr = "npm"

    pkg = _read_package_json(root)
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    env.app_name = pkg.get("name")

    # --- framework (step 3) ---
    if "@angular/core" in deps:
        env.framework = "angular"
        env.ssr = "@angular/ssr" in deps or "@angular/platform-server" in deps
    elif "react" in deps and not (META_FRAMEWORK_DEPS & deps.keys()):
        env.framework = "react"
        if "vite" in deps:
            env.bundler = "vite"
        elif "webpack" in deps:
            env.bundler = "webpack"
        elif "rspack" in deps:
            env.bundler = "rspack"
        elif "parcel" in deps:
            env.bundler = "parcel"
        elif "esbuild" in deps:
            env.bundler = "esbuild"
    elif META_FRAMEWORK_DEPS & deps.keys():
        env.framework = "unsupported"
    else:
        env.framework = "unsupported"

    env.framework_family = {"angular": "angular", "react": "react"}.get(env.framework, "other")

    # --- lint/unit commands (steps 6-7) — recorded, not executed here ---
    scripts = pkg.get("scripts", {})
    if "lint" in scripts:
        env.lint_cmd = f"{env.pkg_mgr} run lint"
    else:
        env.lint_cmd = "npx eslint"

    if "test" in scripts:
        env.unit_cmd = scripts["test"]
    elif "test-ci" in scripts:
        env.unit_cmd = scripts["test-ci"]
    elif "vitest" in deps:
        env.unit_cmd = "npx vitest run"
    else:
        env.unit_cmd = "npx jest"

    # --- test runner (step 8) ---
    cmd = (env.unit_cmd or "").lower()
    if "vitest" in cmd:
        env.test_runner = "vitest"
    elif "jest" in cmd:
        env.test_runner = "jest"
    elif env.framework == "angular" and (root / "karma.conf.js").exists():
        env.test_runner = "jasmine-karma"
    elif "mocha" in cmd:
        env.test_runner = "mocha"

    # --- component test lib (step 9) ---
    if "@testing-library/angular" in deps:
        env.component_test_lib = "@testing-library/angular"
    elif "@testing-library/react" in deps:
        env.component_test_lib = "@testing-library/react"
    elif env.framework == "angular":
        env.component_test_lib = "angular-testbed"

    # --- http mock lib (step 10) ---
    if "msw" in deps:
        env.http_mock_lib = "msw"
    elif "nock" in deps:
        env.http_mock_lib = "nock"
    elif "axios-mock-adapter" in deps:
        env.http_mock_lib = "axios-mock-adapter"
    elif env.framework == "angular":
        env.http_mock_lib = "HttpTestingController"
    elif "cypress" in deps:
        env.http_mock_lib = "cy.intercept"

    env.node_modules_present = (root / "node_modules").is_dir()

    return env
