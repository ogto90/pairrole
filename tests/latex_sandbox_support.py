"""Helpers for integration tests that need Linux namespaces."""

import shutil
import subprocess


def bubblewrap_namespace_unavailable_reason() -> str | None:
    """Return why the host cannot run the real sandbox, or None when it can."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return "bubblewrap is not installed"

    try:
        result = subprocess.run(
            [
                bwrap,
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind", "/usr", "/usr",
                "--proc", "/proc",
                "--dev", "/dev",
                "--", "/usr/bin/true",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"bubblewrap namespace probe failed: {exc}"

    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        return f"bubblewrap namespaces unavailable: {detail or f'exit {result.returncode}'}"
    return None
