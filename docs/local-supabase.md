# Local Supabase operations

The deployment tooling targets a Linux computer using the official Supabase
self-hosted Compose distribution. Container images are pinned in
`deploy/local-supabase/images.lock.yml`; the upstream source commit is pinned in
`scripts/prepare_local_supabase.py`.

The application remains a private, server-configured personal application. It
does not have a login screen. Only loopback ports are published:

| Service | Address |
| --- | --- |
| Streamlit | `http://127.0.0.1:8501` |
| Supabase API and password-protected Studio | `http://127.0.0.1:55321` |
| PostgreSQL | `127.0.0.1:55322` |

Existing development Supabase stacks use different ports and volumes.

## Private deployment state

`.local-supabase/` is ignored by Git and contains credentials, persistent data,
snapshots, logs, and rendered service units. Do not remove it when cleaning a
checkout. Its `runtime/.env` contains Studio credentials and database settings;
`destination.env` contains the application credentials and original owner UUID.
Never paste these files or resolved Compose configuration into logs or issues.

The Compose project is `pairrole-local`. From `.local-supabase/runtime`:

```bash
docker compose -p pairrole-local ps
docker compose -p pairrole-local up -d
```

Do not use `down -v`, upstream `reset.sh`, or `supabase db reset` against this
deployment. The CLI development stack and this production Compose stack are
separate installations.

## Application and scheduled jobs

User services run under the same account as the application, preserving the
filesystem-based CV lifecycle lock. User lingering allows services to continue
after logout. The machine must remain powered on for scheduled jobs.

```bash
systemctl --user status pairrole-app.service
systemctl --user list-timers 'pairrole-*'
journalctl --user -u pairrole-summaries.service -n 40
```

Discovery runs at 10:07 and 18:07 Europe/Vienna, matching the repository's
timezone-aware workflow. Summaries run every 15 minutes and after successful
discovery. Local database/document backups run at 03:30 Europe/Vienna.

The local scheduler refuses to run without `.local-supabase/active`, an explicit
owner UUID, and the exact local API origin. It maintains a persistent ATS rotation
counter. GitHub's two backend-writing workflows are disabled at cutover; the
`PAIRROLE_BACKEND=local` repository variable also guards future versions of the
workflow files. Security workflows remain enabled.

## Backups and recovery

```bash
systemctl --user start pairrole-backup.service
```

Each timestamped directory under `.local-supabase/backups` contains a PostgreSQL
custom archive, its checksum, document bytes indexed by SHA-256, a Storage
manifest, and a `complete` marker written only after success. Snapshot work
coordinates with the application artifact lock. Back up configuration/secrets
as well as data. Backups on this computer do not protect against losing the
computer: configure an encrypted off-host copy separately. Backups are retained;
monitor disk usage and prune only after checking recovery requirements.

Recovery should first be rehearsed in an isolated deployment. The migration
restore script intentionally refuses a non-empty or active target. It restores
application schemas and Auth data while retaining the destination's managed
Auth migration ledger. Storage bytes must be restored through the Storage API.
It resets inherited application privileges before replaying source grants,
because restoring a dump's additive grants alone leaves default client access.

## Migration verification and rollback boundaries

The source is exported read-only. Rehearsal and final snapshots are separate.
The comparison script checks row digests for public/Auth/application migration
tables and checks application functions, columns, constraints, indexes, triggers,
RLS settings and privileges. It explicitly reparses CHECK expressions when
PostgreSQL changes their formatting during restore. Storage verification checks
the complete path inventory and every object's SHA-256.

The online database is retained after cutover. Before accepting local writes,
rollback can restore the protected original environment files and resume the
cloud app/workflows. After local writes begin, rollback requires reconciliation
of changed records and documents; simply restoring the old URL loses changes.

The live migration ledger, not the current working tree, determines the restored
schema. A pending local migration is not silently applied during a hosting move.
Do not replay `supabase/migrations_archive` on either production deployment.

## Validation commands

```bash
.venv/bin/python -m pytest -q tests/test_self_hosted_target.py tests/test_local_migration_guards.py
.venv/bin/python scripts/smoke_local_supabase.py --read-only
```

The smoke test uses real local REST/RPC/Storage endpoints. Without `--read-only`,
it additionally creates and removes a temporary job and document, advancing a
sequence; use that mode during rehearsals. It never invokes an AI provider or
sends email.

## Source configuration

Source identifiers and credentials are supplied privately. Configure a libpq
service in `~/.pg_service.conf` (host, port, database and username) and use
`~/.pgpass` with mode 0600 for its password. Export
`PAIRROLE_SOURCE_DATABASE_SERVICE` with that service's name before running the
database export or source comparison. Source connections require TLS.

For cloud Storage snapshots, pass `--source-env /path/to/private/source.env`
and `--expected-source-url https://YOUR_PROJECT_REF.supabase.co` independently.
The environment file needs `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. Local backups
use `--local-source` and do not require cloud credentials. Never commit private
configuration, dumps, manifests, CVs or job-search exports.

The public repository keeps hosted discovery and summary workflows manual.
On a local deployment, set repository variable `PAIRROLE_BACKEND=local` to block
those writers and use the local timers instead. Migration scripts do not apply
pending migrations automatically; review the migration history before deployment.


## Discovery monitoring and desktop launches

The local checkout, Docker bind mounts, Python virtual environment and service
units all use one `pairrole` directory; no compatibility paths remain.

The Jobs page checks the discovery timer and persisted run history every minute.
It warns when the timer is inactive, a scheduled run is missing, a search failed,
or a run has remained in progress for over three hours. A recent manual search
does not conceal a missed scheduled search.

Local discovery runs at 10:07 and 18:07 Europe/Vienna. Check or restart it with:

```bash
systemctl --user status pairrole-discovery.timer
systemctl --user enable --now pairrole-discovery.timer pairrole-summaries.timer
```

Settings uses the installed Bun runtime even when the desktop launcher has a
minimal PATH. The ATS registry permits the exact local API origin
`http://127.0.0.1:55321`; remote endpoints still require HTTPS, and credentialed
registry requests never follow redirects.
