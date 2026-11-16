#!/usr/bin/env python3
"""Read-only cloud export and fail-closed restore into PairRole's empty local database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import shutil

from local_supabase_storage import STATE, read_env

DESTINATION = "host=127.0.0.1 port=55322 dbname=postgres user=postgres connect_timeout=15"


def source_connection() -> str:
    """Use an explicitly selected private libpq service; never embed account details."""
    service = os.environ.get("PAIRROLE_SOURCE_DATABASE_SERVICE", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", service):
        raise ValueError("Set PAIRROLE_SOURCE_DATABASE_SERVICE to a configured libpq service name")
    return f"service={service} sslmode=require connect_timeout=15"


def permission_reset() -> str:
    statements = []
    for owner in ("postgres", "supabase_admin"):
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            statements.append(f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public REVOKE ALL ON {kind} FROM PUBLIC, anon, authenticated, service_role;")
    for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
        statements.append(f"REVOKE ALL ON ALL {kind} IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role;")
    return "\n".join(statements) + "\n"


def local_env():
    return {**os.environ, "PGPASSWORD": read_env(STATE / "runtime/.env")["POSTGRES_PASSWORD"]}


def sql(query: str, *, source=False) -> str:
    result = subprocess.run(["psql", source_connection() if source else DESTINATION, "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", query],
                            env=os.environ if source else local_env(), capture_output=True, text=True, check=True)
    return result.stdout.strip()


def selected_toc(toc: str, *, schema: bool) -> str:
    selected = []
    for line in toc.splitlines():
        if not line or line.startswith(";"):
            continue
        if schema:
            keep = (" public " in line or " supabase_migrations " in line
                    or "SCHEMA - supabase_migrations " in line
                    or "SCHEMA supabase_migrations " in line
                    or "SCHEMA public " in line)
            keep = keep and "TABLE DATA " not in line and "SEQUENCE SET " not in line
            keep = keep and "SCHEMA - public " not in line
        else:
            keep = any(f"TABLE DATA {s} " in line or f"SEQUENCE SET {s} " in line
                       for s in ("public", "auth", "supabase_migrations"))
            keep = keep and "TABLE DATA auth schema_migrations " not in line
        if keep:
            selected.append(line)
    if not selected:
        raise ValueError("Empty restore selection")
    return "\n".join(selected) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "restore"])
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    folder = args.snapshot.resolve()
    if not folder.is_relative_to(STATE.resolve()):
        parser.error("Snapshot must be inside the private deployment directory")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    dump = folder / "database.dump"
    if args.action == "export":
        if dump.exists():
            parser.error("Refusing to overwrite an existing database export")
        subprocess.run(["pg_dump", source_connection(), "--format=custom", "--file=" + str(dump)], check=True)
    else:
        checksum = folder / "database.sha256"
        if checksum.exists() and hashlib.sha256(dump.read_bytes()).hexdigest() != checksum.read_text().strip():
            parser.error("Database snapshot checksum failed")
        # Refuse import into a database already containing application data or an active deployment.
        if (STATE / "active").exists():
            parser.error("Deployment is active; restore requires a separate recovery target")
        identity = subprocess.check_output(["docker", "inspect", "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}', "pairrole-local-db"], text=True).strip()
        if identity != "pairrole-local":
            parser.error("Unexpected destination container identity")
        count = sql("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public','supabase_migrations')")
        if count != "0" or sql("SELECT count(*) FROM auth.users") != "0":
            parser.error("Destination is not empty; refusing to overwrite application or identity data")
        toc = subprocess.check_output(["pg_restore", "--list", str(dump)], text=True)
        for kind in ["schema", "data"]:
            listing = folder / f"{kind}.list"
            listing.write_text(selected_toc(toc, schema=kind == "schema"))
            subprocess.run(["pg_restore", "--use-list=" + str(listing), "--file=" + str(folder / f"{kind}.sql"), str(dump)], check=True)
        acl_list = folder / "acl.list"
        acl_list.write_text("\n".join(line for line in toc.splitlines()
            if " ACL public " in line or " DEFAULT ACL public " in line or " ACL - SCHEMA public " in line) + "\n")
        subprocess.run(["pg_restore", "--use-list=" + str(acl_list), "--file=" + str(folder / "acl.sql"), str(dump)], check=True)
        # The managed postgres role cannot restore defaults owned by supabase_admin.
        # Use the local container's administrator through its Unix socket only.
        combined = folder / "restore.sql"
        with combined.open("wb") as out:
            out.write(b"CREATE EXTENSION IF NOT EXISTS hypopg WITH SCHEMA extensions VERSION '1.4.1';\n"
                      b"CREATE EXTENSION IF NOT EXISTS index_advisor WITH SCHEMA extensions VERSION '0.2.0';\n")
            with (folder / "schema.sql").open("rb") as part:
                shutil.copyfileobj(part, out)
            # pg_dump ACLs are additive against a fresh Supabase stack's defaults.
            # Clear inherited grants and replay the source ACLs exactly.
            out.write(permission_reset().encode())
            with (folder / "acl.sql").open("rb") as part:
                shutil.copyfileobj(part, out)
            out.write(b"\nSET session_replication_role = replica;\n")
            with (folder / "data.sql").open("rb") as part:
                shutil.copyfileobj(part, out)
            out.write(b"\nSET session_replication_role = origin;\nNOTIFY pgrst, 'reload schema';\n")
        with (folder / "restore.log").open("w") as log, combined.open("rb") as data:
            subprocess.run(["docker", "exec", "-i", "pairrole-local-db", "psql", "-U", "supabase_admin",
                "-d", "postgres", "-X", "--single-transaction", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                stdin=data, stdout=log, stderr=log, check=True)
    (folder / "database.sha256").write_text(hashlib.sha256(dump.read_bytes()).hexdigest() + "\n")
    print(f"Database {args.action} completed; private logs and checksum are in the snapshot directory.")


if __name__ == "__main__":
    main()
