import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from local_supabase_database import selected_toc
from local_supabase_storage import API
import run_local_backend_job as worker


def test_restore_preserves_managed_auth_migrations():
    toc = "\n".join([
        "1; 0 0 TABLE DATA auth users postgres",
        "2; 0 0 TABLE DATA auth schema_migrations postgres",
        "3; 0 0 TABLE DATA storage objects postgres",
        "4; 0 0 TABLE DATA public jobs postgres",
        "5; 0 0 TABLE DATA supabase_migrations schema_migrations postgres",
        "6; 0 0 SEQUENCE SET public jobs_id_seq postgres",
    ])
    result = selected_toc(toc, schema=False)
    assert "auth users" in result
    assert "auth schema_migrations" not in result
    assert "storage objects" not in result
    assert "supabase_migrations schema_migrations" in result
    assert "SEQUENCE SET" in result


def test_restore_schema_excludes_platform_but_keeps_public_permissions():
    toc = "\n".join([
        "1; 0 0 SCHEMA - public postgres", "2; 0 0 TABLE public jobs postgres",
        "3; 0 0 TABLE auth users postgres", "4; 0 0 ACL public TABLE jobs postgres",
        "5; 0 0 DEFAULT ACL public DEFAULT PRIVILEGES FOR TABLES postgres",
        "6; 0 0 SCHEMA - supabase_migrations postgres",
    ])
    result = selected_toc(toc, schema=True)
    assert "SCHEMA - public" not in result
    assert "TABLE auth" not in result
    assert "ACL public" in result
    assert "SCHEMA - supabase_migrations" in result


@pytest.mark.parametrize("url", ["https://example.supabase.co", "http://127.0.0.1:54321", "http://localhost:55321"])
def test_storage_restore_never_targets_other_backends(url):
    with pytest.raises(ValueError):
        API({"SUPABASE_URL": url, "SUPABASE_SECRET_KEY": "test"}, destination=True)


def test_scheduler_cannot_run_before_cutover(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "STATE", tmp_path)
    with pytest.raises(RuntimeError, match="not active"):
        worker.job_environment()


def test_scheduler_rejects_cloud_even_if_activated(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "STATE", tmp_path)
    (tmp_path / "active").touch()
    (tmp_path / "destination.env").write_text("SUPABASE_URL=https://example.supabase.co\n")
    with pytest.raises(RuntimeError, match="destination"):
        worker.job_environment()


def test_cloud_database_source_requires_explicit_private_service(monkeypatch):
    from local_supabase_database import source_connection

    monkeypatch.delenv("PAIRROLE_SOURCE_DATABASE_SERVICE", raising=False)
    with pytest.raises(ValueError, match="PAIRROLE_SOURCE_DATABASE_SERVICE"):
        source_connection()
    monkeypatch.setenv("PAIRROLE_SOURCE_DATABASE_SERVICE", "migration-source")
    assert source_connection() == "service=migration-source sslmode=require connect_timeout=15"
    monkeypatch.setenv("PAIRROLE_SOURCE_DATABASE_SERVICE", "source host=unexpected")
    with pytest.raises(ValueError):
        source_connection()
