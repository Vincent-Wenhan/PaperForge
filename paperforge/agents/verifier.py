"""Verifier: check generated app builds and matches PRD."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.observability.metrics import get_metrics
from paperforge.sandbox.build_runner import BuildRunner
from paperforge.schemas.verification import VerificationReport
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

# Target Repair V2 (doc 22.1): match TS error paths like app/page.tsx:12
TS_ERROR_RE = re.compile(
    r"(?P<path>"
    r"(?:app|components|hooks|lib|types)"
    r"/[^:(\s]+"
    r")"
    r"(?:\(|:)"
    r"(?P<line>\d+)"
)

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
    L4 Runtime readiness is checked after the preview sandbox becomes ready.
    L5 Product acceptance is checked by the bounded browser smoke runner.

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
    build_result = None
    try:
        runner = BuildRunner(mode="docker")
        build_result = await runner.run(app_path)
    except Exception:
        runner = BuildRunner(mode="local")
        build_result = await runner.run(app_path)

    if build_result.ok:
        build_succeeded = True
    else:
        build_succeeded = False
    build_errors.extend(build_result.errors)
    build_warnings.extend(build_result.warnings)

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
    # PRD V2: flat `features` list (doc 8.2). Fall back to legacy priority lists.
    if prd.get("features"):
        prd_features = [f.get("name", "") for f in prd["features"]]
    else:
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
        for _file_path, content in files:
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
    has_acceptance_criteria = bool(prd.get("acceptance_criteria"))
    acceptance_status = (
        "failed"
        if missing_features
        else "pending"
        if prd_id and has_acceptance_criteria
        else "passed"
    )

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

    # Hard gates (doc 24): a failed gate cannot be overridden by score.
    workspace_ok = has_package_json and has_app_dir and has_page
    typecheck_ok = not type_errors
    build_ok = build_succeeded
    lint_ok = not lint_errors
    security_ok = not security_issues
    gates = {
        "workspace_ok": workspace_ok,
        "typecheck_ok": typecheck_ok,
        "build_ok": build_ok,
        "lint_ok": lint_ok,
        "security_ok": security_ok,
        "runtime_ok": None,
        "acceptance_ok": acceptance_status != "failed",
    }
    technical_ready = all([
        gates["workspace_ok"],
        gates["typecheck_ok"],
        gates["build_ok"],
        gates["security_ok"],
    ])
    preview_allowed = gates["workspace_ok"] and gates["build_ok"]
    product_ready = technical_ready and gates["runtime_ok"] is True and gates["acceptance_ok"] is True

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

    layers = [
        {
            "id": "workspace",
            "name": "Workspace integrity",
            "status": "passed" if has_package_json and has_app_dir and has_page else "failed",
            "errors": list(build_errors),
            "security_issues": list(security_issues),
        },
        {
            "id": "static",
            "name": "Static quality",
            "status": "passed" if not type_errors and not lint_errors else "failed",
            "type_errors": list(type_errors),
            "lint_errors": list(lint_errors),
        },
        {
            "id": "build",
            "name": "Build",
            "status": "passed" if build_succeeded else "failed",
            "environment": build_result.environment,
            "degraded": build_result.degraded,
            "fallback_reason": build_result.fallback_reason,
        },
        {
            "id": "runtime",
            "name": "Runtime readiness",
            "status": "pending",
            "reason": "Checked after run_in_sandbox reports an HTTP-ready preview.",
        },
        {
            "id": "acceptance",
            "name": "Product acceptance",
            "status": acceptance_status,
            "prd_coverage": prd_coverage,
            "missing_features": list(missing_features),
            "reason": "Browser smoke runs after the preview is ready."
            if prd_id
            else "No PRD acceptance criteria supplied.",
        },
    ]

    report = {
        "app_id": app_id,
        "prd_id": prd_id,
        "layers": layers,
        "build_environment": build_result.environment,
        "build_degraded": build_result.degraded,
        "build_fallback_reason": build_result.fallback_reason,
        "runtime_status": "pending",
        "acceptance_status": acceptance_status,
        "browser_smoke": {},
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
        "gates": gates,
        "technical_ready": technical_ready,
        "preview_allowed": preview_allowed,
        "product_ready": product_ready,
        "overall_score": score,
        "ready_for_preview": preview_allowed,
        "recommendations": recommendations,
    }

    try:
        validated = VerificationReport.model_validate(report)
        report = validated.model_dump()
    except Exception as e:
        logger.warning(f"Schema validation failed: {e}. Using raw report.")

    return report


async def build_and_repair(
    app_path: str | Path,
    prd_id: str | None,
    llm: LLMClient,
    storage: Storage,
    *,
    max_attempts: int = MAX_REPAIR_ROUNDS,
) -> dict[str, Any]:
    """Generate → Verify → Repair loop.

    For each attempt:
      1. Run ``verify_app`` to get a fresh report.
      2. If ``technical_ready`` is true, return the report (doc 24).
      3. Otherwise, snapshot the workspace, ask the LLM for a patch
         that fixes the top build/type/lint errors, apply it, and
         re-verify.

    The function always returns the most recent verification report,
    even if repair did not succeed within ``max_attempts``.
    """
    app_path = Path(app_path)
    attempts: list[dict[str, Any]] = []
    latest_report: dict[str, Any] = {}

    for attempt in range(1, max_attempts + 1):
        started_at = time.monotonic()
        report = await verify_app(
            app_path=app_path,
            prd_id=prd_id,
            llm=llm,
            storage=storage,
        )
        elapsed = time.monotonic() - started_at
        latest_report = report
        try:
            get_metrics().record_duration("verify_duration_ms", elapsed)
        except Exception:
            pass

        attempts.append({
            "attempt": attempt,
            "elapsed_s": round(elapsed, 2),
            "build_succeeded": report.get("build_succeeded"),
            "type_errors": len(report.get("type_errors", [])),
            "lint_errors": len(report.get("lint_errors", [])),
            "overall_score": report.get("overall_score"),
            "ready_for_preview": report.get("ready_for_preview"),
            "technical_ready": report.get("technical_ready"),
        })

        # Hard-gate loop exit: a TypeScript/build/security error can't be
        # overridden by a high score, so stop once the gates pass (doc 24).
        if report.get("technical_ready"):
            break

        # Snapshot before patching so we can roll back.
        snapshot_dir = app_path.with_name(f"{app_path.name}.attempt_{attempt}")
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        shutil.copytree(app_path, snapshot_dir)

        try:
            patched = await _apply_repair_patch(
                app_path=app_path,
                report=report,
                llm=llm,
            )
            if not patched:
                # Could not produce a patch; stop early to avoid wasting
                # attempts on the same error.
                break
        except Exception as exc:
            logger.warning(f"Repair attempt {attempt} failed: {exc}")
            shutil.rmtree(app_path)
            shutil.copytree(snapshot_dir, app_path)
            break

    latest_report["repair_attempts"] = attempts
    return latest_report


async def _apply_repair_patch(
    app_path: Path,
    report: dict[str, Any],
    llm: LLMClient,
) -> bool:
    """Ask the LLM for a patch that fixes the top errors in the report.

    Returns ``True`` if a patch was applied, ``False`` otherwise. The
    patch is restricted to the same writable roots as the generator
    (SafeWorkspacePolicy) so a hallucinating model cannot write arbitrary
    files.

    Uses targeted repair (doc 22): instead of sending every workspace file
    to the LLM, we seed the repair context from the error paths in the
    report, then expand it to include each file's local ``@/`` dependencies
    (bounded to ~12 files).
    """
    from paperforge.config import get_config
    from paperforge.prompts import load_prompt
    from paperforge.schemas.workspace_policy import (
        SafeWorkspacePolicy,
        WorkspacePatch,
        apply_workspace_patch,
    )

    policy = SafeWorkspacePolicy()

    # Collect the most actionable errors. Type errors and build errors
    # are the ones the LLM can usually fix in a single pass.
    errors: list[str] = []
    errors.extend(report.get("build_errors", [])[:8])
    errors.extend(report.get("type_errors", [])[:8])
    errors.extend(report.get("lint_errors", [])[:8])
    if not errors:
        return False

    # Targeted context: seed from error paths, expand local @/ dependencies.
    seed_paths = extract_error_paths(errors)
    selected = seed_paths
    if selected:
        try:
            selected = expand_repair_context(app_path, seed_paths)
        except OSError:
            return False
    else:
        # No parseable error paths (e.g. missing toolchain / opaque errors).
        # Fall back to a broad workspace scan so repair still can proceed.
        selected = [rel for rel, _ in collect_files(app_path)]

    relevant_files: list[dict[str, str]] = []
    for rel in selected:
        try:
            policy.normalize(rel)
            content = (app_path / rel).read_text(encoding="utf-8")
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        relevant_files.append({"path": rel, "content": content})
    if not relevant_files:
        return False

    prompt = load_prompt("repair_agent")
    user_content = json.dumps({
        "errors": errors,
        "files": relevant_files,
    }, ensure_ascii=False, indent=2)

    cfg = get_config()
    response = await llm.chat(
        model=cfg.GENERATOR_MODEL,
        messages=[
            Message(role="system", content=prompt),
            Message(role="user", content=user_content),
        ],
        response_format={"type": "json_object"},
    )

    content = response.content or "{}"
    try:
        patch = WorkspacePatch.model_validate_json(content)
    except Exception:
        return False

    if not patch.files:
        return False

    try:
        apply_workspace_patch(app_path, patch, policy)
    except ValueError as exc:
        logger.warning(f"Repair patch rejected by policy: {exc}")
        return False

    return True


def extract_error_paths(errors: list[str]) -> list[str]:
    """Return unique file paths referenced by TS/type error messages (doc 22.1)."""
    result: list[str] = []
    for error in errors:
        for match in TS_ERROR_RE.finditer(error):
            path = match.group("path")
            if path not in result:
                result.append(path)
    return result


def expand_repair_context(
    workspace: Path,
    seed_paths: list[str],
    *,
    max_files: int = 12,
) -> list[str]:
    """Expand seed error paths to include their local ``@/`` dependencies (doc 22.2)."""
    from paperforge.agents.generation_v3 import (
        import_to_paths,
        parse_local_imports,
    )

    selected = list(seed_paths)

    cursor = 0
    while cursor < len(selected) and len(selected) < max_files:
        path = selected[cursor]
        cursor += 1

        source_path = workspace / path
        if not source_path.is_file():
            continue

        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for module in parse_local_imports(source):
            for candidate in import_to_paths(module):
                if (workspace / candidate).is_file() and candidate not in selected:
                    selected.append(candidate)
                    break
                if len(selected) >= max_files:
                    break

    return selected[:max_files]


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


async def run_command_stream(
    command: list[str],
    cwd: Path,
    *,
    timeout_s: float,
    on_line: Any = None,
) -> CommandResult:
    """Run a command, streaming stdout/stderr to ``on_line`` (doc 26).

    ``timeout_s`` bounds the whole process wait, not each log callback, so a
    totally silent hung process still times out. Unifies the old ``_exec``
    (non-streaming) and ``_exec_streaming`` paths.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return CommandResult(returncode=-1, stderr=f"Command not found: {command[0]}")
    except Exception as e:  # noqa: BLE001
        return CommandResult(returncode=-1, stderr=f"Execution error: {e}")

    assert proc.stdout is not None
    captured: list[str] = []

    async def consume() -> None:
        async for raw in proc.stdout:
            text = raw.decode("utf-8", errors="replace")
            captured.append(text)
            if on_line:
                await on_line(text)

    consumer = asyncio.create_task(consume())
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        try:
            await proc.wait()
        except ProcessLookupError:
            pass
    finally:
        await consumer

    return CommandResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout="".join(captured),
        timed_out=timed_out,
    )


async def _exec(
    cmd: list[str],
    cwd: Path,
    timeout: int,
) -> tuple[bool, str, str]:
    result = await run_command_stream(cmd, cwd, timeout_s=timeout)
    ok = result.returncode == 0 and not result.timed_out
    err = result.stderr
    if result.timed_out:
        err = err or f"Command timed out after {timeout}s"
    return ok, result.stdout, err


async def _exec_streaming(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    on_line: Any,
) -> tuple[bool, str]:
    """Run a command, streaming each line to ``on_line`` (doc 26)."""
    result = await run_command_stream(cmd, cwd, timeout_s=timeout, on_line=on_line)
    return result.returncode == 0 and not result.timed_out, result.stdout


async def _run_checks_streaming(
    app_path: Path,
    timeout: int,
    progress: Any,
    step_id: str,
) -> tuple[bool, list[str]]:
    """Run typecheck + lint, streaming each line through progress.step_progress.

    Returns ``(ok, errors)`` where errors are the filtered actionable lines.
    """
    errors: list[str] = []

    async def cb(text: str) -> None:
        line = text.strip()
        if not line:
            return
        await progress.progress(step_id, detail=line[:400])
        if "error" in line.lower() or "failed" in line.lower():
            errors.append(line)

    for cmd in (
        ["npx", "--no-install", "tsc", "--noEmit"],
        ["npm", "run", "lint", "--silent"],
    ):
        _, _ = await _exec_streaming(cmd, app_path, timeout, cb)
    return len(errors) == 0, errors


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
