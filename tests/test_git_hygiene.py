from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path, PurePosixPath


GENERATED_OR_LOCAL_PREFIXES = (
    ".deepeval/",
    ".pytest_cache/",
    ".test-tmp/",
    "tests/_runtime/",
    "_runtime/",
    "_external/",
    ".venv/",
    "node_modules/",
    "frontend/node_modules/",
    ".next/",
    "frontend/.next/",
    "playwright-report/",
    "frontend/playwright-report/",
    "test-results/",
    "frontend/test-results/",
    "coverage/",
    "htmlcov/",
    ".mypy_cache/",
    ".ruff_cache/",
    "playwright/.cache/",
    "frontend/playwright/.cache/",
    "_video_analysis/",
    "resume_render/",
)

GENERATED_OR_LOCAL_EXACT = {
    ".coverage",
    ".env",
    "ads-agent-draft.json",
}

GENERATED_OR_LOCAL_GLOBS = (
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.pid",
    "*.sqlite",
    "*.sqlite3",
    "*.tsbuildinfo",
    ".env.*",
    "frontend/.env*.local",
    "frontend/tsconfig*.tsbuildinfo",
)

REQUIRED_GITIGNORE_PATTERNS = (
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".deepeval/",
    ".test-tmp/",
    ".test-tmp-*/",
    "tests/_runtime/",
    "_runtime/",
    "_external/",
    ".venv/",
    "node_modules/",
    ".next/",
    "playwright-report/",
    "test-results/",
    "dist/",
    "build/",
    "*.log",
    "*.pid",
    "*.tsbuildinfo",
    "*.sqlite3",
    "*.sqlite",
    "coverage/",
    "htmlcov/",
    ".coverage",
    ".mypy_cache/",
    ".ruff_cache/",
    "playwright/.cache/",
    "frontend/tsconfig*.tsbuildinfo",
    "frontend/.env*.local",
    "ads-agent-draft.json",
    ".env",
    ".env.*",
    "!.env.example",
)

REQUIRED_GITATTRIBUTES_PATTERNS = (
    "* text=auto",
    "*.py text eol=lf",
    "*.ts text eol=lf",
    "*.tsx text eol=lf",
    "*.js text eol=lf",
    "*.json text eol=lf",
    "*.md text eol=lf",
    "*.css text eol=lf",
    "*.yml text eol=lf",
    "*.yaml text eol=lf",
    "*.png binary",
    "*.jpg binary",
    "*.jpeg binary",
    "*.gif binary",
    "*.webp binary",
    "*.ico binary",
    "*.sqlite binary",
    "*.sqlite3 binary",
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        check=True,
        text=True,
    )
    return [line.replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def test_generated_runtime_and_secret_artifacts_are_not_tracked() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        name = PurePosixPath(path).name
        if path == ".env.example":
            continue
        if path in GENERATED_OR_LOCAL_EXACT:
            offenders.append(path)
            continue
        if any(path.startswith(prefix) for prefix in GENERATED_OR_LOCAL_PREFIXES):
            offenders.append(path)
            continue
        if any(
            fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern)
            for pattern in GENERATED_OR_LOCAL_GLOBS
        ):
            offenders.append(path)

    assert not offenders, "Generated, local, or secret files are tracked: " + ", ".join(offenders)


def test_gitignore_covers_runtime_frontend_and_secret_artifacts() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")
    missing = [pattern for pattern in REQUIRED_GITIGNORE_PATTERNS if pattern not in text]

    assert not missing, "Missing .gitignore patterns: " + ", ".join(missing)


def test_gitattributes_normalizes_source_text_and_binary_assets() -> None:
    text = Path(".gitattributes").read_text(encoding="utf-8")
    missing = [pattern for pattern in REQUIRED_GITATTRIBUTES_PATTERNS if pattern not in text]

    assert not missing, "Missing .gitattributes patterns: " + ", ".join(missing)


def test_github_project_governance_files_exist() -> None:
    required = [
        Path(".github/workflows/ci.yml"),
        Path(".github/pull_request_template.md"),
        Path(".github/ISSUE_TEMPLATE/agent_quality.md"),
        Path(".github/ISSUE_TEMPLATE/config.yml"),
    ]

    for path in required:
        assert path.exists(), f"{path} should exist for GitHub project governance."

    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest tests -q" in ci
    assert "npm run lint --prefix frontend" in ci
    assert "npm run test:smoke --prefix frontend" in ci
    assert "--spend-credits" not in ci
    assert "--media-buyer-deepeval" not in ci

    pr_template = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
    for marker in [
        "Agent Surface",
        "Safety",
        "Evidence",
        "read-only or draft-only",
        "bounded step limit",
    ]:
        assert marker in pr_template

    issue_template = Path(".github/ISSUE_TEMPLATE/agent_quality.md").read_text(encoding="utf-8")
    for marker in [
        "Tools called",
        "Trace ID",
        "Decision card",
        "Draft safety",
    ]:
        assert marker in issue_template
