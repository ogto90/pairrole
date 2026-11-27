"""Read-only monitoring of the local discovery schedule and persisted runs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
VIENNA = ZoneInfo('Europe/Vienna')


@st.cache_data(ttl=30, show_spinner=False)
def scheduler_state() -> dict[str, str]:
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'show', 'pairrole-discovery.timer',
             'pairrole-discovery.service', '--property=Id,ActiveState,Result,ExecMainExitTimestamp,NextElapseUSecRealtime'],
            capture_output=True, text=True, timeout=3, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {'timer': 'unknown'}
    state = {}
    for block in result.stdout.strip().split('\n\n'):
        values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if values.get('Id') == 'pairrole-discovery.timer':
            state['timer'] = values.get('ActiveState', 'unknown')
            state['next'] = values.get('NextElapseUSecRealtime', '')
        elif values.get('Id') == 'pairrole-discovery.service':
            state['service'] = values.get('ActiveState', 'unknown')
            state['result'] = values.get('Result', '')
            state['finished'] = values.get('ExecMainExitTimestamp', '')
    try:
        scheduled = json.loads((ROOT / '.local-supabase/discovery-status.json').read_text())
        state['scheduled_started'] = scheduled['started_at']
        state['scheduled_status'] = scheduled['status']
    except (OSError, ValueError, KeyError, TypeError):
        state['scheduled_started'] = ''
    return state


def health_warnings(state: dict, latest: dict | None, now: datetime) -> list[str]:
    warnings = []
    if state.get('timer') == 'unknown' or 'timer' not in state:
        warnings.append('Automatic discovery status could not be checked. The schedule may not be running.')
    elif state['timer'] != 'active':
        warnings.append('Automatic discovery is stopped. Scheduled searches will not run until the local timer is restarted.')
    if state.get('result') not in (None, '', 'success'):
        warnings.append('The last scheduled discovery failed. Open Settings to retry and review search diagnostics.')
    # Allow 15 minutes for a scheduled search to start before calling it missed.
    cutoff = now.astimezone(VIENNA) - timedelta(minutes=15)
    slots = [
        (cutoff - timedelta(days=day)).replace(hour=hour, minute=7, second=0, microsecond=0)
        for day in (0, 1) for hour in (10, 18)
    ]
    expected = max(slot for slot in slots if slot <= cutoff)
    if state.get('timer') == 'active' and state.get('service') != 'activating' and 'scheduled_started' in state:
        try:
            scheduled = datetime.fromisoformat(state['scheduled_started'].replace('Z', '+00:00'))
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            missed = scheduled < expected
        except (ValueError, TypeError, AttributeError):
            missed = True
        if missed:
            warnings.append('The timer is active, but its latest scheduled search was not recorded. Check the local discovery service.')
    if state.get('scheduled_status') == 'failed' and state.get('result') in (None, '', 'success'):
        warnings.append('The last scheduled search failed. Open Settings to retry.')
    try:
        started = datetime.fromisoformat(latest['started_at'].replace('Z', '+00:00'))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except (TypeError, KeyError, ValueError):
        warnings.append('No recent discovery run could be verified. Search results may be out of date.')
        return warnings
    if started < expected:
        warnings.append(f'Discovery is overdue: no search has been recorded since the scheduled {expected:%d %b, %H:%M %Z} run.')
    if latest.get('status') == 'running' and now - started > timedelta(hours=3):
        warnings.append('The last search has been marked in progress for over three hours and may have stopped.')
    elif latest.get('status') == 'failed':
        warnings.append('The latest search failed. Open Settings to retry.')
    return warnings


def render_discovery_health(project_url: str, latest: dict | None) -> None:
    if urlparse(project_url).hostname not in {'localhost', '127.0.0.1'} or not (ROOT / '.local-supabase/active').is_file():
        return
    state = scheduler_state()
    for warning in health_warnings(state, latest, datetime.now(timezone.utc)):
        st.warning(warning)
    if state.get('timer') == 'active':
        st.caption('Automatic discovery: active · daily at 10:07 and 18:07 Vienna time. This computer and the local backend must be running.')
    if state.get('finished'):
        outcome = 'succeeded' if state.get('result') == 'success' else 'failed'
        st.caption(f"Last scheduled process: {state['finished']} · {outcome}")
