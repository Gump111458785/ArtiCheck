from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import time
import uuid
from pathlib import Path


class Sandbox:
    """Docker is the default. Local mode is ONLY for trusted, user-owned fixtures."""
    def __init__(self, mode="docker", image="python:3.11-slim", timeout=30, output_limit=1_000_000):
        if mode not in {"docker", "local"}:
            raise ValueError("Unknown sandbox mode")
        self.mode, self.image, self.timeout = mode, image, timeout
        self.output_limit = output_limit

    async def identity(self):
        if self.mode == "local":
            import sys
            return {"mode": "local_trusted", "python": sys.version, "timeout": self.timeout}
        if not shutil.which("docker"):
            raise RuntimeError("Docker unavailable; install Docker or explicitly use --sandbox local for trusted fixtures")
        process = await asyncio.create_subprocess_exec(shutil.which("docker"), "image", "inspect", "--format", "{{.Id}}", self.image,
                                                     stdout=-1, stderr=-1)
        out, _ = await asyncio.wait_for(process.communicate(), 15)
        if process.returncode:
            raise RuntimeError("Docker image missing; pull/build the configured image explicitly")
        return {"mode": "docker", "image_id": out.decode().strip(), "timeout": self.timeout,
                "network": "none", "memory": "1g", "cpus": "1"}

    def docker_command(self, repo: Path, argv: list[str], name: str):
        return [shutil.which("docker") or "docker", "run", "--rm", "--name", name, "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=128",
                "--memory=1g", "--cpus=1", "--user=65534:65534", "--init",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=64m", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "--mount", f"type=bind,source={repo.resolve()},target=/artifact,readonly",
                "--workdir=/artifact", self.image, *argv]

    async def execute(self, repo: Path, argv: list[str]):
        if not argv or not all(isinstance(x, str) and "\0" not in x for x in argv):
            raise ValueError("Expected an argv list")
        name = "articheck-" + uuid.uuid4().hex
        # The trusted Docker CLIENT needs its configured daemon/context. Host
        # variables are not forwarded into the container without explicit -e.
        env = None if self.mode == "docker" else {
            "PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        command = self.docker_command(repo, argv, name) if self.mode == "docker" else argv
        started = time.monotonic()
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = await asyncio.create_subprocess_exec(*command, cwd=repo, env=env,
                                                          stdout=stdout, stderr=stderr, start_new_session=True)
            timed_out, overflow = False, False
            try:
                while process.returncode is None:
                    if time.monotonic() - started > self.timeout:
                        timed_out = True
                        break
                    if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > self.output_limit:
                        overflow = True
                        break
                    try:
                        await asyncio.wait_for(process.wait(), .05)
                    except asyncio.TimeoutError:
                        pass
            finally:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
                if self.mode == "docker":
                    cleanup = await asyncio.create_subprocess_exec(shutil.which("docker") or "docker", "rm", "-f", name, stdout=-3, stderr=-3)
                    await cleanup.wait()
            overflow |= os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > self.output_limit
            stdout.seek(0)
            stderr.seek(0)
            out = stdout.read(self.output_limit).decode(errors="replace")
            err = stderr.read(self.output_limit).decode(errors="replace")
        success = process.returncode == 0 and not timed_out and not overflow
        payload = None
        if success:
            try:
                payload = json.loads(out, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                success = isinstance(payload, dict)
            except ValueError:
                success = False
        return {"success": success, "payload": payload if success else {}, "stdout": out,
                "stderr": err, "returncode": process.returncode, "timed_out": timed_out,
                "output_overflow": overflow, "elapsed_seconds": time.monotonic() - started}
