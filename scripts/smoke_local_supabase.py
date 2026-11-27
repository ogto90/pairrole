#!/usr/bin/env python3
"""Exercise real local REST/RPC/Storage paths with the application client; no AI calls."""
import argparse
import json
import sys
from uuid import uuid4

from local_supabase_storage import LOCAL_URL, ROOT, STATE, read_env, object_path
from local_supabase_database import sql
from prepare_local_supabase import jwt

sys.path.insert(0, str(ROOT))
from matching.candidate_profile_persistence import SupabaseRestClient, PersistenceError
from ui.profile_data import load_profile_context
from ui.dashboard_summary import fetch_dashboard_page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", help="Skip temporary CRUD writes after final cutover")
    args = parser.parse_args()
    settings = read_env(STATE / "destination.env")
    assert settings["SUPABASE_URL"] == LOCAL_URL
    client = SupabaseRestClient(LOCAL_URL, settings["SUPABASE_SECRET_KEY"])
    user = settings["PAIRROLE_USER_ID"]
    context = load_profile_context(client, user)
    assert context["cv"] and context["candidate"] and context["search_profile"]
    base = client.resolve_active_base_cv(user)
    assert client.download_storage_object(base.storage_bucket, base.file_path)
    for view in ("Pending / unresolved", "Needs attention", "Ready to apply", "Applied", "Archived"):
        page = fetch_dashboard_page(client, user_id=user, filters={"view": view})
        assert page.user_id == user
    assert client.get_json("/rest/v1/interview_preparations?select=id&limit=1")
    assert client.get_json("/rest/v1/interview_preparation_packs?select=preparation_id&limit=1")
    runtime = read_env(STATE / "runtime/.env")
    tables = json.loads(sql("SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public'"))
    for role in ("anon", "authenticated"):
        restricted = SupabaseRestClient(LOCAL_URL, runtime["ANON_KEY"])
        bearer = runtime["ANON_KEY"] if role == "anon" else jwt(runtime["JWT_SECRET"], role)
        for table in tables:
            try:
                restricted.request("GET", f"/rest/v1/{table}?select=*&limit=1",
                                   extra_headers={"Authorization": "Bearer " + bearer})
            except PersistenceError as exc:
                assert "HTTP 401" in str(exc) or "HTTP 403" in str(exc), str(exc)
            else:
                raise AssertionError(f"Unexpected {role} table access: {table}")
        try:
            restricted.request("GET", object_path(base.storage_bucket, base.file_path),
                               extra_headers={"Authorization": "Bearer " + bearer})
        except PersistenceError:
            pass
        else:
            raise AssertionError("Private CV accessible to an unprivileged role")
    accessible = sql("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND (has_function_privilege('anon',p.oid,'EXECUTE') OR has_function_privilege('authenticated',p.oid,'EXECUTE'))")
    assert accessible == "0", "Public function execution differs from the server-only model"
    table_access = sql("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r' AND (has_table_privilege('anon',c.oid,'SELECT') "
        "OR has_table_privilege('authenticated',c.oid,'SELECT'))")
    assert table_access == "0", "Unexpected client table privileges"
    if args.read_only:
        print("Read-only local smoke passed: application data, dashboard RPCs, CV download, server-only permissions.")
        return
    token = str(uuid4())
    job = None
    path = f"{user}/migration-smoke/{token}.txt"
    try:
        job = client.json_request("POST", "/rest/v1/jobs", {
            "source": "manual_history", "company": "Migration smoke " + token, "title": "Test role",
        }, prefer="return=representation")[0]
        assert int(job["id"]) > 4290
        client.json_request("PATCH", f"/rest/v1/jobs?id=eq.{job['id']}", {"title": "Updated test role"})
        assert client.get_json(f"/rest/v1/jobs?id=eq.{job['id']}&select=title")[0]["title"] == "Updated test role"
        client.upload_storage_object("cv-artifacts", path, b"local migration smoke", content_type="text/plain")
        assert client.download_storage_object("cv-artifacts", path) == b"local migration smoke"
    finally:
        client.delete_storage_object("cv-artifacts", path)
        if job:
            client.json_request("DELETE", f"/rest/v1/jobs?id=eq.{job['id']}")
    print("Local smoke passed: profile, base CV, 5 dashboard views, saved interviews, REST CRUD, Storage roundtrip, 56 denied table reads and restricted RPCs.")


if __name__ == "__main__":
    main()
