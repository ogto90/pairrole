from urllib.parse import parse_qs, urlparse

import pytest

from matching.candidate_profile_persistence import PersistenceError
from ui.discovery_history import (
    format_discovery_started_at,
    load_latest_discovery,
    render_latest_discovery,
)


@pytest.fixture(autouse=True)
def clear_discovery_history_cache():
    load_latest_discovery.clear()


def test_latest_discovery_query_is_user_scoped_and_returns_minimal_fields():
    class Client:
        base_url = "https://project.example"

        def get_json(self, path):
            query = parse_qs(urlparse(path).query)
            assert query["select"] == ["user_id,started_at,status"]
            assert query["user_id"] == ["eq.user-a"]
            assert query["order"] == ["started_at.desc,id.desc"]
            assert query["limit"] == ["1"]
            return [{
                "user_id": "user-a",
                "started_at": "2026-11-04T11:07:00+00:00",
                "status": "completed",
            }]

    assert load_latest_discovery(
        Client(), user_id="user-a", project_url="https://project.example"
    ) == {"started_at": "2026-11-04T11:07:00+00:00", "status": "completed"}


def test_latest_discovery_returns_none_when_no_runs_exist():
    class Client:
        def get_json(self, path):
            return []

    assert load_latest_discovery(Client(), user_id="user-a", project_url="empty") is None


def test_latest_discovery_rejects_rows_outside_user_scope():
    class Client:
        def get_json(self, path):
            return [{
                "user_id": "user-b",
                "started_at": "2026-11-04T11:07:00+00:00",
                "status": "completed",
            }]

    with pytest.raises(PersistenceError, match="scope"):
        load_latest_discovery(Client(), user_id="user-a", project_url="scope-test")


def test_discovery_time_is_formatted_in_vienna_local_time():
    assert format_discovery_started_at("2026-11-04T11:07:00Z") == "4 Nov 2026, 12:07 CET"


def test_invalid_discovery_time_has_safe_fallback():
    assert format_discovery_started_at("invalid") == "time unavailable"


def test_jobs_notice_includes_local_time_and_run_status(monkeypatch):
    import streamlit as st

    class Client:
        def get_json(self, path):
            return [{
                "user_id": "user-a",
                "started_at": "2026-11-04T11:07:00Z",
                "status": "partial",
            }]

    captions = []
    monkeypatch.setattr(st, "caption", captions.append)
    render_latest_discovery(Client(), user_id="user-a", project_url="render-test")

    assert captions == ["Last discovery: 4 Nov 2026, 12:07 CET · completed with issues"]
