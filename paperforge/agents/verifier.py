"""Verifier: check generated app builds and matches PRD."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.verification import VerificationReport
from paperforge.sandbox.build_runner import BuildRunner
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)

# Patterns for security scan
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub PAT
]
DANGEROUS_PATTERNS = [
    (re.compile(r"dangerouslySetInnerHTML"), "dangerouslySetInnerHTML usage"),
    (re.compile(r"\beval\s*\("), "eval() usage"),
    (re.compile(r"new\s+Function\s*\("), "new Function() usage"),
]

MAX_REPAIR_ROUNDS = 3
TYPECHECK_TIMEOUT = 120
LINT_TIMEOUT = 120


async def verify_app(
    app_path: str | Path,
    prd_id: str | None,
    llm: LLMClient,
    storage: Storage,
) -> dict[str, Any]:
    """Verify a generated Next.js app across five layers.

    L1 Workspace integrity (files, secrets, dangerous APIs)
    L2 Static quality (TypeScript via tsc --noEmit, ESLint via next lint)
    L3 Build (npm ci + next build, prefers Docker if available)
    L4 Runtime readiness is deferred to run_in_sandbox
    L5 Product acceptance is delegated to a future acceptance-test runner

    Returns a verification report dict.
    """
    app_path = Path(app_path)
    app_id = app_path.name

    files = collect_files(app_path)

    # L1: Workspace integrity
    has_package_json = any(f[0] == "package.json" for f in files)
    has_app_dir = any(f[0].startswith("app/") for f in files)
    has_page = any(f[0] in ["app/page.tsx", "app/page.jsx", "app/page.js"] for f in files)

    build_succeeded = has_package_json and has_app_dir and has_page
    build_errors: list[str] = []
    build_warnings: list[str] = []
    type_errors: list[str] = []
    lint_errors: list[str] = []
    if not has_package_json:
        build_errors.append("Missing package.json")
    if not has_app_dir:
        build_errors.append("Missing app/ directory")
    if not has_page:
        build_errors.append("Missing app/page.tsx")

    # L3: Real build via unified BuildRunner.
    try:
        runner = BuildRunner(mode="docker")
        result = await runner.run(app_path)
    except Exception:
        runner = BuildRunner(mode="local")
        result = await runner.run(app_path)

    if result.ok:
        build_succeeded = True
    else:
        build_succeeded = False
    build_errors.extend(result.errors)
    build_warnings.extend(result.warnings)

    # L2: Static quality (only run if structure check passed)
    if has_package_json:
        tc_ok, tc_out, tc_err = await _exec(
            ["npx", "--no-install", "tsc", "--noEmit"],
            app_path,
            TYPECHECK_TIMEOUT,
        )
        if not tc_ok:
            for line in (tc_out + "\n" + tc_err).splitlines():
                if line.strip():
                    type_errors.append(line.strip())

        lint_ok, lint_out, lint_err = await _exec(
            ["npm", "run", "lint", "--silent"],
            app_path,
            LINT_TIMEOUT,
        )
        if not lint_ok:
            for line in (lint_out + "\n" + lint_err).splitlines():
                if line.strip():
                    lint_errors.append(line.strip())

    # L1b: PRD coverage
    prd: dict[str, Any] = {}
    if prd_id:
        artifact = storage.get_artifact(prd_id)
        if artifact:
            prd = artifact.get("data") or {}

    prd_features = []
    for key in ("must_have", "should_have", "could_have"):
        for f in prd.get(key, []):
            prd_features.append(f.get("name", ""))

    missing_features: list[str] = []
    extra_features: list[str] = []
    covered = 0
    for feature in prd_features:
        keywords = [w.lower() for w in feature.split() if len(w) > 3]
        if not keywords:
            continue
        found = False
        for file_path, content in files:
            content_lower = content.lower()
            if any(k in content_lower for k in keywords):
                found = True
                break
        if found:
            covered += 1
        else:
            missing_features.append(feature)

    total = len(prd_features) or 1
    prd_coverage = covered / total

    # L1c: Mock/Real boundary
    mock_files = [f for f in files if "mock" in f[0].lower()]
    real_files = [f for f in files if "real" in f[0].lower()]
    mock_count = len(mock_files)
    real_count = len(real_files)
    boundary_clear = mock_count > 0 and real_count > 0
    boundary_issues: list[str] = []
    if not boundary_clear:
        boundary_issues.append("Mock and real adapters not clearly separated")

    # L1d: Security scan
    security_issues: list[str] = []
    for file_path, content in files:
        for pattern in SECRET_PATTERNS:
            matches = pattern.findall(content)
            for m in matches:
                security_issues.append(f"Hardcoded secret in {file_path}: {m[:10]}...")

        for pattern, msg in DANGEROUS_PATTERNS:
            if pattern.search(content):
                security_issues.append(f"{msg} in {file_path}")

    # Calculate score
    score = 0.0
    if build_succeeded:
        score += 0.4
    score += 0.3 * prd_coverage
    if boundary_clear:
        score += 0.2
    security_penalty = min(len(security_issues) / 10, 0.1)
    score += 0.1 - security_penalty

    ready_for_preview = build_succeeded and score >= 0.6

    recommendations: list[str] = []
    if missing_features:
        recommendations.append(f"Add missing features: {', '.join(missing_features[:3])}")
    if security_issues:
        recommendations.append("Remove hardcoded secrets and dangerous APIs")
    if not boundary_clear:
        recommendations.append("Separate mock and real adapters into distinct files")
    if type_errors:
        recommendations.append(f"Fix {len(type_errors)} TypeScript error(s)")
    if lint_errors:
        recommendations.append(f"Fix {len(lint_errors)} lint error(s)")
    if not recommendations:
        recommendations.append("App looks good. Ready for preview.")

    report = {
        "app_id": app_id,
        "prd_id": prd_id,
        "build_succeeded": build_succeeded,
        "build_errors": build_errors,
        "build_warnings": build_warnings,
        "prd_coverage": prd_coverage,
        "missing_features": missing_features,
        "extra_features": extra_features,
        "mock_adapters_count": mock_count,
        "real_adapters_count": real_count,
        "boundary_clear": boundary_clear,
        "boundary_issues": boundary_issues,
        "type_errors": type_errors,
        "lint_errors": lint_errors,
        "security_issues": security_issues,
        "overall_score": score,
        "ready_for_preview": ready_for_preview,
        "recommendations": recommendations,
    }

    try:
        validated = VerificationReport.model_validate(report)
        report = validated.model_dump()
    except Exception as e:
        logger.warning(f"Schema validation failed: {e}. Using raw report.")

    return report


async def _exec(
    cmd: list[str],
    cwd: Path,
    timeout: int,
) -> tuple[bool, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, "", f"Command timed out after {timeout}s"

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        return proc.returncode == 0, stdout_text, stderr_text
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, "", f"Execution error: {e}"


def collect_files(root: Path) -> list[tuple[str, str]]:
    """Collect all source files in the app directory."""
    files: list[tuple[str, str]] = []
    if not root.exists():
        return files

    skip_dirs = {"node_modules", ".next", ".git", "dist", "build"}
    skip_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot"}

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in skip_exts:
            continue

        try:
            content = path.read_text(encoding="utf-8")
            rel_path = str(path.relative_to(root)).replace("\\", "/")
            files.append((rel_path, content))
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")

    return files
