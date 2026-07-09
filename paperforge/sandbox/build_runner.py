"""Unified BuildRunner.

Single entry point for `npm install` + `npm run build` on a generated
Next.js app. Both the Verifier and the DockerSandboxManager use this to
avoid duplicate build logic and divergent results.

Build modes:
  - "docker": run install+build inside a throwaway Docker container.
              Used by the verifier when Docker is available.
  - "local":  run install+build as host subprocesses. Fallback when
              Docker is not available.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from paperforge.config import get_config

logger = logging.getLogger(__name__)

BuildMode = Literal["docker", "local"]


@dataclass
class BuildResult:
    """Outcome of a BuildRunner.run() call."""

    ok: bool = False
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    environment: str = "local"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    install_succeeded: bool = False
    build_succeeded: bool = False


class BuildRunner:
    """Run `npm install` + `npm run build` in a chosen environment."""

    def __init__(self, mode: BuildMode = "local") -> None:
        self.mode = mode

    async def run(
        self,
        app_path: Path,
        install_timeout: int = 300,
        build_timeout: int = 300,
    ) -> BuildResult:
        """Execute install + build and return a unified BuildResult."""
        app_path = Path(app_path)
        result = BuildResult(environment=self.mode)

        if not (app_path / "package.json").exists():
            result.errors.append("package.json not found")
            return result

        if self.mode == "docker":
            return await self._run_in_docker(app_path, result, install_timeout, build_timeout)
        return await self._run_local(app_path, result, install_timeout, build_timeout)

    async def _run_local(
        self,
        app_path: Path,
        result: BuildResult,
        install_timeout: int,
        build_timeout: int,
    ) -> BuildResult:
        # npm install
        install_ok, install_stdout, install_stderr = await self._exec(
            ["npm", "install", "--no-audit", "--no-fund"],
            app_path,
            install_timeout,
        )
        result.install_succeeded = install_ok
        result.stdout += install_stdout
        result.stderr += install_stderr
        if not install_ok:
            result.errors.append("npm install failed")
            for line in install_stderr.splitlines():
                if "error" in line.lower() or "failed" in line.lower():
                    result.errors.append(line.strip())
            return result

        # npm run build
        build_ok, build_stdout, build_stderr = await self._exec(
            ["npm", "run", "build"],
            app_path,
            build_timeout,
        )
        result.build_succeeded = build_ok
        result.stdout += build_stdout
        result.stderr += build_stderr
        if not build_ok:
            combined = build_stdout + "\n" + build_stderr
            for line in combined.splitlines():
                if "error" in line.lower() or "failed" in line.lower():
                    result.errors.append(line.strip())
            return result

        for line in build_stderr.splitlines():
            if "warning" in line.lower():
                result.warnings.append(line.strip())

        result.ok = True
        return result

    async def _run_in_docker(
        self,
        app_path: Path,
        result: BuildResult,
        install_timeout: int,
        build_timeout: int,
    ) -> BuildResult:
        try:
            import docker
            from docker.errors import DockerException
        except ImportError:
            logger.warning("Docker SDK not available, falling back to local build")
            self.mode = "local"
            result.environment = "local"
            return await self._run_local(app_path, result, install_timeout, build_timeout)

        cfg = get_config()
        try:
            client = docker.from_env()
            client.ping()
        except (DockerException, Exception) as e:
            logger.warning(f"Docker not available ({e}), falling back to local build")
            self.mode = "local"
            result.environment = "local"
            return await self._run_local(app_path, result, install_timeout, build_timeout)

        container_name = f"paperforge-build-{asyncio.get_event_loop().time_ns()}"
        try:
            container = client.containers.create(
                image=cfg.SANDBOX_IMAGE,
                command="sh -c 'npm install --no-audit --no-fund && npm run build'",
                volumes={str(app_path.resolve()): {"bind": "/app", "mode": "rw"}},
                working_dir="/app",
                detach=True,
                name=container_name,
            )
            container.start()

            # Poll container status until it exits or times out
            elapsed = 0
            while True:
                container.reload()
                if container.status != "running":
                    break
                if elapsed > install_timeout + build_timeout:
                    container.kill()
                    result.errors.append("Docker build timed out")
                    return result
                await asyncio.sleep(2)
                elapsed += 2

            logs = container.logs().decode("utf-8", errors="replace")
            exit_code = container.attrs["State"].get("ExitCode")

            result.exit_code = exit_code
            result.stdout = logs
            if exit_code == 0:
                result.ok = True
                result.install_succeeded = True
                result.build_succeeded = True
            else:
                for line in logs.splitlines():
                    if "error" in line.lower() or "failed" in line.lower():
                        result.errors.append(line.strip())
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass

        return result

    async def _exec(
        self,
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
            return False, "", "npm not found in PATH"
        except Exception as e:
            return False, "", f"Execution error: {e}"
