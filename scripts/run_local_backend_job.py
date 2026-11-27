#!/usr/bin/env python3
"""Run a local scheduled job only after cutover has explicitly activated this deployment."""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys

from local_supabase_storage import LOCAL_URL, ROOT, STATE, read_env


def job_environment() -> dict[str, str]:
    if not (STATE / "active").is_file():
        raise RuntimeError("Local deployment is not active; scheduled work is disabled")
    values = read_env(STATE / "destination.env")
    if values.get("SUPABASE_URL") != LOCAL_URL or values.get("PAIRROLE_EXPECTED_SUPABASE_URL") != LOCAL_URL:
        raise RuntimeError("Local scheduler destination does not match the fixed deployment origin")
    if not values.get("PAIRROLE_USER_ID"):
        raise RuntimeError("Local scheduler requires an explicit owner UUID")
    env = {**os.environ, **values}
    env["PATH"] = str(Path.home() / ".bun/bin") + os.pathsep + env.get("PATH", "")
    env["PAIRROLE_ATS_REGISTRY_SOURCE"] = "supabase"
    env["PAIRROLE_ATS_REGISTRY_MIN_VERIFIED"] = "1"
    env["PAIRROLE_TRACING_ENABLED"] = "false"
    env["PAIRROLE_JD_ENRICHMENT_MAX_ATTEMPTS"] = "30"
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=["discovery", "summaries"])
    args = parser.parse_args()
    env = job_environment()
    os.umask(0o077)
    with (STATE / f"{args.job}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("This job is already running; skipping duplicate execution.")
            return 0
        status = STATE / "discovery-status.json"
        if args.job == "discovery":
            counter = STATE / "ats-rotation"
            slot = int(counter.read_text()) + 1 if counter.exists() else 1
            temporary = counter.with_suffix(".tmp")
            temporary.write_text(str(slot))
            temporary.replace(counter)
            env["PAIRROLE_ATS_ROTATION_SLOT"] = str(slot)
            subprocess.run([sys.executable, str(ROOT / "scripts/run_dashboard_discovery.py"),
                "--status-file", str(status), "--log-file", str(STATE / "discovery.log"),
                "--user-id", env["PAIRROLE_USER_ID"]], cwd=ROOT, env=env, check=True, timeout=7200)
        command = [sys.executable, str(ROOT / "scripts/build_dashboard_summaries.py"),
            "--supabase-url", LOCAL_URL, "--expected-url", LOCAL_URL,
            "--user-id", env["PAIRROLE_USER_ID"], "--retries", "3", "--require-complete"]
        if args.job == "discovery":
            command += ["--discovery-status-file", str(status)]
        subprocess.run(command, cwd=ROOT, env=env, check=True, timeout=1500)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
