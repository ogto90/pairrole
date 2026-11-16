import pytest

from scripts.build_dashboard_summaries import validate_target


def test_self_hosted_exact_origin():
    assert validate_target("http://127.0.0.1:55321/", expected_url="http://127.0.0.1:55321") == "http://127.0.0.1:55321"


@pytest.mark.parametrize("actual", [
    "http://127.0.0.1:54321", "https://127.0.0.1:55321", "http://localhost:55321",
    "http://127.0.0.1:55321/rest/v1", "http://user:secret@127.0.0.1:55321",
    "http://127.0.0.1:55321?target=cloud", "http://127.0.0.1:55321#fragment",
    "http://127.0.0.1:invalid",
])
def test_self_hosted_rejects_wrong_origin(actual):
    with pytest.raises(ValueError):
        validate_target(actual, expected_url="http://127.0.0.1:55321")


def test_cloud_protection_cannot_be_bypassed_with_expected_url():
    url = "https://example-project.supabase.co"
    with pytest.raises(ValueError, match="allow-production"):
        validate_target(url, expected_url=url)
    assert validate_target(url, project_ref="example-project", allow_production=True) == url


def test_legacy_local_and_ambiguous_targets():
    assert validate_target("http://localhost:54321", project_ref="local") == "http://localhost:54321"
    with pytest.raises(ValueError):
        validate_target("http://localhost:55321", project_ref="local")
    with pytest.raises(ValueError):
        validate_target("http://localhost:54321", project_ref="local", expected_url="http://localhost:54321")
