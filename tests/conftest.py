import pytest


@pytest.fixture(autouse=True)
def _skip_summary_algorithm_version_sync(monkeypatch, request):
    """Strict mock Supabase clients only expect the RPCs a test exercises.

    Tests of the sync itself opt out with @pytest.mark.summary_version_sync.
    """
    if request.node.get_closest_marker("summary_version_sync"):
        return
    try:
        import ui.dashboard_summary as dashboard_summary
    except Exception:  # pragma: no cover - module import errors surface in its own tests
        return
    monkeypatch.setattr(dashboard_summary, "sync_summary_algorithm_version", lambda client: None)
