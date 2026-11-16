#!/usr/bin/env python3
"""Create a private local database + document backup. An off-host copy is still required."""
import datetime
import hashlib
import os
import subprocess
import sys

from local_supabase_database import DESTINATION, local_env
from local_supabase_storage import LOCAL_URL, ROOT, STATE
from run_local_backend_job import job_environment

sys.path.insert(0, str(ROOT))
from matching.artifact_lifecycle_lock import artifact_lifecycle_lock


def main():
    job_environment()  # Fail closed before cutover or if the target is misconfigured.
    os.umask(0o077)
    folder = STATE / "backups" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, mode=0o700)
    # Coordinate with the app's document cleanup so referenced files survive the snapshot.
    with artifact_lifecycle_lock(LOCAL_URL, timeout=60):
        dump = folder / "database.dump"
        subprocess.run(["pg_dump", DESTINATION, "--format=custom", "--file=" + str(dump)], env=local_env(), check=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/local_supabase_storage.py"), "snapshot", "--local-source",
            "--snapshot", str(folder)], check=True)
    subprocess.run(["pg_restore", "--list", str(dump)], check=True, stdout=subprocess.DEVNULL)
    (folder / "database.sha256").write_text(hashlib.sha256(dump.read_bytes()).hexdigest() + "\n")
    (folder / "complete").touch()
    print("Local database and document backup completed. Backups remain on this computer.")


if __name__ == "__main__":
    main()
