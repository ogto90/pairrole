#!/usr/bin/env python3
"""Compare source and destination records, SQL definitions, grants and identity data read-only."""
import argparse
import json
import os
from pathlib import Path

from local_supabase_database import sql
from local_supabase_storage import STATE

CATALOG = """
SELECT jsonb_build_object(
 'tables', (SELECT jsonb_agg(jsonb_build_array(c.relname,c.relrowsecurity,c.relforcerowsecurity,
    pg_get_userbyid(c.relowner),c.relacl::text) ORDER BY c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'),
 'functions', (SELECT jsonb_agg(jsonb_build_array(p.proname,pg_get_function_identity_arguments(p.oid),
    pg_get_functiondef(p.oid),p.proacl::text,pg_get_userbyid(p.proowner)) ORDER BY p.proname,pg_get_function_identity_arguments(p.oid))
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'),
 'columns', (SELECT jsonb_agg(jsonb_build_array(table_name,column_name,data_type,is_nullable,column_default,is_identity)
    ORDER BY table_name,ordinal_position) FROM information_schema.columns WHERE table_schema='public'),
 'constraints', (SELECT jsonb_agg(jsonb_build_array(c.conname,c.conrelid::regclass::text,pg_get_constraintdef(c.oid))
    ORDER BY c.conrelid::regclass::text,c.conname) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public'),
 'indexes', (SELECT jsonb_agg(jsonb_build_array(tablename,indexname,indexdef) ORDER BY indexname)
    FROM pg_indexes WHERE schemaname='public'),
 'triggers', (SELECT jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) ORDER BY c.relname,t.tgname)
    FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND NOT t.tgisinternal),
 'policies', (SELECT jsonb_agg(to_jsonb(p) ORDER BY tablename,policyname) FROM pg_policies p WHERE schemaname='public'),
 'defaults', (SELECT jsonb_agg(jsonb_build_array(pg_get_userbyid(d.defaclrole),d.defaclobjtype,d.defaclacl::text)
    ORDER BY pg_get_userbyid(d.defaclrole),d.defaclobjtype) FROM pg_default_acl d JOIN pg_namespace n ON n.oid=d.defaclnamespace WHERE n.nspname='public')
);
"""


def inventory(*, source):
    catalog = json.loads(sql("SET timezone='UTC'; " + CATALOG, source=source))
    tables = json.loads(sql("SELECT json_agg(json_build_array(schemaname,tablename) ORDER BY schemaname,tablename) FROM pg_tables WHERE schemaname IN ('public','auth','supabase_migrations') AND NOT (schemaname='auth' AND tablename='schema_migrations')", source=source))
    result = {}
    for schema, table in tables:
        ident = '.'.join('"' + s.replace('"', '""') + '"' for s in (schema, table))
        result[schema + '.' + table] = json.loads(sql(
            "SET timezone='UTC'; SELECT json_build_object('count',count(*),'digest',"
            "md5(coalesce(string_agg(h,'' ORDER BY h),''))) FROM "
            f"(SELECT md5(to_jsonb(t)::text) h FROM {ident} t) rows", source=source))
    return {"catalog": catalog, "tables": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.report.resolve().is_relative_to(STATE.resolve()):
        parser.error("Report must remain in private deployment state")
    os.umask(0o077)
    source = inventory(source=True)
    target = inventory(source=False)
    differences = []
    normalized_checks = []
    # PostgreSQL can flatten associative AND expressions when reparsing a dump.
    # Reparse differing CHECKs on an empty temporary clone, rather than ignoring text differences.
    for src, dst in zip(source["catalog"]["constraints"], target["catalog"]["constraints"]):
        if src[:2] == dst[:2] and src[2] != dst[2] and src[2].startswith("CHECK ("):
            table = '"' + src[1].removeprefix('public.').replace('"', '""') + '"'
            canonical = sql("BEGIN; CREATE TEMP TABLE migration_check (LIKE public." + table + "); "
                "ALTER TABLE migration_check ADD CONSTRAINT migration_source_check " + src[2] + "; "
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='migration_check'::regclass "
                "AND conname='migration_source_check'; ROLLBACK;")
            if canonical == dst[2]:
                src[2] = canonical
                normalized_checks.append(src[0])
    for category in source["catalog"]:
        if source["catalog"][category] != target["catalog"][category]:
            differences.append("catalog." + category)
    for table in source["tables"].keys() | target["tables"].keys():
        if source["tables"].get(table) != target["tables"].get(table):
            differences.append(table)
    args.report.write_text(json.dumps({"source": source, "destination": target, "differences": sorted(differences),
        "checks_verified_by_reparse": normalized_checks}, indent=2) + "\n")
    print(f"Compared {len(source['tables'])} tables and {len(source['catalog'])} schema categories.")
    if differences:
        print("Differences: " + ", ".join(sorted(differences)))
        raise SystemExit(1)
    print("All row counts, row digests and application schema categories match.")


if __name__ == "__main__":
    main()
