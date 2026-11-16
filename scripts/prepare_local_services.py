#!/usr/bin/env python3
"""Render reviewable user service units; does not install or activate them."""
import os
from local_supabase_storage import ROOT, STATE


def main():
    os.umask(0o077)
    folder = STATE / "systemd"
    folder.mkdir(mode=0o700, exist_ok=True)
    python = ROOT / ".venv/bin/python"
    common = f"""[Unit]
Description=PairRole {{description}}
ConditionPathExists={STATE}/active

[Service]
Type={{type}}
WorkingDirectory={ROOT}
EnvironmentFile={STATE}/destination.env
Environment=PATH={ROOT}/.venv/bin:{os.path.expanduser('~')}/.bun/bin:/usr/local/bin:/usr/bin:/bin
UMask=0077
ExecStart={{command}}
{{extra}}
"""
    services = {
        "pairrole-app": ("local application", "simple",
            f"{python} -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true",
            "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target"),
        "pairrole-discovery": ("local discovery", "oneshot",
            f"{python} scripts/run_local_backend_job.py discovery", "TimeoutStartSec=3h"),
        "pairrole-summaries": ("local summary refresh", "oneshot",
            f"{python} scripts/run_local_backend_job.py summaries", "TimeoutStartSec=30min"),
        "pairrole-backup": ("local database and document backup", "oneshot",
            f"{python} scripts/backup_local_supabase.py", "TimeoutStartSec=1h"),
    }
    for name, (description, kind, command, extra) in services.items():
        (folder / f"{name}.service").write_text(common.format(description=description, type=kind, command=command, extra=extra))
    for name, calendar in {
        "pairrole-discovery": "*-*-* 10,18:07:00 Europe/Vienna",
        "pairrole-summaries": "*:0/15",
        "pairrole-backup": "*-*-* 03:30:00 Europe/Vienna",
    }.items():
        (folder / f"{name}.timer").write_text(f"""[Unit]
Description=Schedule {name}

[Timer]
OnCalendar={calendar}
Persistent=true
Unit={name}.service

[Install]
WantedBy=timers.target
""")
    print("Rendered 4 services and 3 timers without installing or activating them.")


if __name__ == "__main__":
    main()
