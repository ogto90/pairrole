#!/usr/bin/env python3
"""Build compact dashboard summaries in resumable batches of at most 50.

Run after applying the dashboard-summary migration and after profile changes.
This command is intentionally separate from Streamlit page requests.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from matching.candidate_profile_persistence import (
    PersistenceError,
    SupabaseRestClient,
)
from ui.dashboard_summary import build_dashboard_summaries


def validate_target(url: str, *, project_ref: str | None = None,
                    expected_url: str | None = None, allow_production: bool = False) -> str:
    """Validate an exact deployment origin without weakening legacy target guards."""
    url = url.rstrip("/")
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid API port") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.params or parsed.query or parsed.fragment):
        raise ValueError("Supabase URL must be an HTTP(S) origin without credentials, path, query or fragment")
    if bool(project_ref) == bool(expected_url):
        raise ValueError("Specify exactly one expected project reference or expected URL")
    if expected_url is not None:
        if url != expected_url.rstrip("/"):
            raise ValueError("Supabase URL does not match the expected deployment URL")
    elif project_ref == "local":
        if parsed.hostname not in {"127.0.0.1", "localhost"} or port != 54321:
            raise ValueError("The local target must be http(s)://localhost:54321")
    elif parsed.hostname != f"{project_ref}.supabase.co":
        raise ValueError("Supabase URL host does not match the expected project reference")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and not allow_production:
        raise ValueError("Refusing to write dashboard summaries to production without --allow-production")
    return url


def discovery_job_ids(status_path: Path) -> list[int]:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    runs = (status.get("result") or {}).get("runs") or []
    return sorted({
        int(job_id)
        for run in runs if isinstance(run, dict)
        for job_id in (run.get("processedJobIds") or [])
        if str(job_id).isdigit() and int(job_id) > 0
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supabase-url", required=True, help="Exact disposable or approved Supabase API URL to target.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--expected-project-ref", help="Expected Supabase project ref, or 'local' for localhost:54321.")
    target.add_argument("--expected-url", help="Exact independently configured API origin for a self-hosted deployment.")
    parser.add_argument("--user-id", default=os.getenv("AI_JOB_SEARCH_USER_ID"))
    parser.add_argument("--max-batches", type=int, help="Stop after this many 50-job batches; rerun to resume.")
    parser.add_argument(
        "--discovery-status-file", type=Path,
        help="Prioritize processed job ids from a run_dashboard_discovery.py status file.",
    )
    parser.add_argument(
        "--require-complete", action="store_true",
        help="Return failure if selected summaries remain pending after this run.",
    )
    parser.add_argument("--retries", type=int, default=3, help="Retries after transient failures (default: 3).")
    parser.add_argument("--allow-production", action="store_true", help="Explicitly allow writes to a hosted Supabase project.")
    args = parser.parse_args()
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches must be positive")
    if args.retries < 0 or args.retries > 5:
        parser.error("--retries must be between 0 and 5")
    priority_job_ids = None
    if args.discovery_status_file is not None:
        try:
            priority_job_ids = discovery_job_ids(args.discovery_status_file)
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            parser.error(f"Could not read discovered job ids from the status file: {exc}")
    url = args.supabase_url.rstrip("/")
    secret = os.getenv("DASHBOARD_SUMMARY_SUPABASE_SECRET_KEY")
    if not args.user_id or not secret:
        parser.error("Set DASHBOARD_SUMMARY_SUPABASE_SECRET_KEY and AI_JOB_SEARCH_USER_ID or pass --user-id")
    try:
        url = validate_target(url, project_ref=args.expected_project_ref,
                              expected_url=args.expected_url, allow_production=args.allow_production)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = SupabaseRestClient(url, secret)
    for attempt in range(args.retries + 1):
        try:
            if client.base_url != url:
                raise PersistenceError("Builder client endpoint does not match the explicitly configured target.")
            result = build_dashboard_summaries(
                client, user_id=args.user_id, max_batches=args.max_batches,
                priority_job_ids=priority_job_ids,
            )
            break
        except (PersistenceError, ValueError) as exc:
            if attempt >= args.retries:
                logging.error("Dashboard summary build failed after %d attempt(s): %s", attempt + 1, exc)
                return 1
            delay = min(2 ** attempt, 8)
            logging.warning("Dashboard summary attempt %d failed; retrying in %ds: %s", attempt + 1, delay, exc)
            time.sleep(delay)
    print(f"Batches: {result['batches']} · saved: {result['saved']} · changed during build: {result['stale']}")
    if result["remaining"] or result["stale"]:
        print("Summaries remain pending or changed during construction. Rerun this command to resume safely.")
        if args.require_complete:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
