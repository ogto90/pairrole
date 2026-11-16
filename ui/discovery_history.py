"""Small user-scoped reads for the most recent persisted discovery run."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import streamlit as st

from matching.candidate_profile_persistence import PersistenceError, SupabaseRestClient


VIENNA = ZoneInfo("Europe/Vienna")


@st.cache_data(ttl=30, max_entries=128, show_spinner=False)
def load_latest_discovery(
    _client: SupabaseRestClient, *, user_id: str, project_url: str,
) -> dict[str, str] | None:
    """Read only the latest run timestamp and status for the current user."""

    rows = _client.get_json("/rest/v1/search_runs?" + urlencode({
        "select": "user_id,started_at,status",
        "user_id": f"eq.{user_id}",
        "order": "started_at.desc,id.desc",
        "limit": "1",
    }))
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or str(row.get("user_id")) != user_id
        for row in rows
    ):
        raise PersistenceError("Supabase returned invalid discovery history scope data.")
    if not rows:
        return None
    row = rows[0]
    started_at = row.get("started_at")
    status = row.get("status")
    if not isinstance(started_at, str) or not started_at.strip():
        raise PersistenceError("Supabase returned a discovery run without a start time.")
    if not isinstance(status, str):
        raise PersistenceError("Supabase returned a discovery run without a status.")
    return {"started_at": started_at, "status": status}


def format_discovery_started_at(value: str) -> str:
    """Format a database timestamp in the app's configured Vienna timezone."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return "time unavailable"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(VIENNA)
    return f"{local.day} {local:%b %Y, %H:%M %Z}"


def render_latest_discovery(
    client: SupabaseRestClient, *, user_id: str, project_url: str,
) -> None:
    """Render a compact last-run notice without making dashboard failures fatal."""

    try:
        latest = load_latest_discovery(client, user_id=user_id, project_url=project_url)
    except (PersistenceError, ValueError, TypeError):
        st.caption("Latest discovery time is currently unavailable.")
        return
    if latest is None:
        st.caption("No discovery runs recorded yet.")
        return

    timestamp = format_discovery_started_at(latest["started_at"])
    labels = {
        "running": "in progress",
        "completed": "completed",
        "partial": "completed with issues",
        "failed": "failed",
    }
    status = labels.get(latest["status"], "status unknown")
    st.caption(f"Last discovery: {timestamp} · {status}")
