import subprocess
import sys
import logging
import time
import tempfile
from pathlib import Path
from core.config import config

log = logging.getLogger("sandbox")


class SandboxError(Exception):
    pass


def validate_syntax(code: str) -> str | None:
    """Validate Python syntax using compile(). Returns error string or None if valid."""
    try:
        compile(code, "<generated>", "exec")
        return None
    except SyntaxError as e:
        msg = f"SyntaxError at line {e.lineno}: {e.msg}"
        if e.text:
            msg += f"\n  Code: {e.text.strip()}"
        log.error("[SANDBOX] Syntax validation failed: %s", msg)
        return msg


def execute(code: str, expected_output: str) -> str:
    log.info("=" * 60)
    log.info("[SANDBOX] Starting code execution")
    log.info("[SANDBOX] Expected output: %s", expected_output)
    log.info("[SANDBOX] Code size: %d chars, %d lines", len(code), code.count("\n") + 1)

    generated_dir = Path(config.generated_dir).resolve()
    generated_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=str(generated_dir),
        delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        script_path = f.name

    log.info("[SANDBOX] Temp script: %s", script_path)
    log.info("[SANDBOX] Timeout: %ds", config.sandbox_timeout)
    log.info("[SANDBOX] Running...")

    try:
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=config.sandbox_timeout,
            cwd=str(generated_dir),
        )
        elapsed = time.time() - t0

        if proc.stdout:
            for line in proc.stdout.strip().split("\n")[:10]:
                log.info("[SANDBOX] stdout: %s", line)
        if proc.stderr:
            for line in proc.stderr.strip().split("\n")[:10]:
                log.warning("[SANDBOX] stderr: %s", line)

        if proc.returncode != 0:
            log.error("[SANDBOX] Script FAILED (exit code %d) after %.1fs", proc.returncode, elapsed)
            raise SandboxError(f"Script failed (exit {proc.returncode}): {proc.stderr[-500:]}")

        if not Path(expected_output).exists():
            log.error("[SANDBOX] Output file NOT FOUND: %s", expected_output)
            raise SandboxError(f"Output file not created: {expected_output}")

        file_size = Path(expected_output).stat().st_size
        log.info("[SANDBOX] SUCCESS in %.1fs — output: %s (%d bytes)", elapsed, expected_output, file_size)
        return expected_output

    except subprocess.TimeoutExpired:
        log.error("[SANDBOX] TIMEOUT after %ds", config.sandbox_timeout)
        raise SandboxError(f"Script timed out after {config.sandbox_timeout}s")
    finally:
        try:
            Path(script_path).unlink()
        except OSError:
            pass
