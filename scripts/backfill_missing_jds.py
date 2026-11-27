#!/usr/bin/env python3
"""Fetch missing job descriptions for listings waiting in Needs attention.

Selects the same jobs the dashboard's "Fetch JD" / "Retry evidence" buttons
would accept, lacking a full JD, and runs the existing liveness + JD-hydration
tool (tools/process_pending_job_evidence.ts) on them in batches of 25. No AI Fit
runs. The dashboard rebuilds its summaries automatically afterwards.

    python scripts/backfill_missing_jds.py            # dry run: list candidates
    python scripts/backfill_missing_jds.py --apply    # fetch and save JDs
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from matching.candidate_profile_persistence import SupabaseRestClient, load_env_file  # noqa: E402
from ui.dashboard_data import DashboardJob, can_retry_pending_evidence  # noqa: E402
from ui.dashboard_summary import fetch_dashboard_page  # noqa: E402
from ui.profile_data import resolve_application_user_id  # noqa: E402

BATCH_SIZE = 25
MAX_PAGES = 200


def has_full_jd(job: DashboardJob) -> bool:
    return job.description_kind == "full"


def select_candidates(jobs: list[DashboardJob]) -> list[DashboardJob]:
    seen: set[int] = set()
    selected = []
    for job in jobs:
        if job.id in seen or has_full_jd(job) or not can_retry_pending_evidence(job):
            continue
        seen.add(job.id)
        selected.append(job)
    return selected


def needs_attention_jobs(client: SupabaseRestClient, user_id: str) -> list[DashboardJob]:
    jobs: list[DashboardJob] = []
    for page in range(1, MAX_PAGES + 1):
        result = fetch_dashboard_page(client, user_id=user_id, filters={"view": "Needs attention", "page": page})
        jobs.extend(result.jobs)
        if not result.jobs or page * result.page_size >= result.total_count:
            break
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="fetch and save JDs (default: dry run)")
    args = parser.parse_args()

    load_env_file(ROOT / ".env")  # fills os.environ without overriding existing values
    url = os.environ.get("SUPABASE_URL", "").strip()
    secret = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not url or not secret:
        print("SUPABASE_URL and SUPABASE_SECRET_KEY must be set (for example in .env).", file=sys.stderr)
        return 2
    client = SupabaseRestClient(url, secret)
    user_id = resolve_application_user_id(client)

    candidates = select_candidates(needs_attention_jobs(client, user_id))
    print(f"{len(candidates)} listing(s) in Needs attention can have their JD fetched.")
    for job in candidates:
        print(f"  #{job.id:<6} {job.source:<18} {job.company[:28]:<28} {job.title[:50]}")
    if not args.apply or not candidates:
        if candidates:
            print("Dry run only. Re-run with --apply to fetch and save JDs.")
        return 0

    # Imported late: the Streamlit dashboard module is heavy and only needed here.
    from ui.dashboard import run_pending_evidence_retry

    totals = {"checked": 0, "full_jd": 0, "expired": 0, "failed_batches": 0}
    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        label = f"batch {start // BATCH_SIZE + 1} ({len(batch)} jobs)"
        try:
            result = run_pending_evidence_retry([job.id for job in batch], user_id=user_id)
        except Exception as exc:  # keep going; one bad batch should not stop the rest
            totals["failed_batches"] += 1
            print(f"{label}: failed: {exc}", file=sys.stderr)
            continue
        rows = result.get("jobs", [])
        full = sum(1 for row in rows if row.get("description_kind") == "full")
        expired = sum(1 for row in rows if row.get("persisted_availability") == "expired")
        totals["checked"] += len(rows)
        totals["full_jd"] += full
        totals["expired"] += expired
        print(f"{label}: {full} full JD, {expired} expired, {len(rows) - full - expired} still without a full JD")
    print(
        f"Done: {totals['checked']} checked, {totals['full_jd']} now have a full JD, "
        f"{totals['expired']} expired, {totals['failed_batches']} failed batch(es)."
    )
    return 1 if totals["failed_batches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
