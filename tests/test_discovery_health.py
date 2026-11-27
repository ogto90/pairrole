from datetime import datetime
import subprocess

from ui.discovery_health import health_warnings, scheduler_state

NOW = datetime.fromisoformat('2026-11-27T12:00:00+01:00')


def test_stopped_timer_warns_even_with_recent_manual_search():
    warnings = health_warnings({'timer': 'inactive'},
        {'started_at': NOW.isoformat(), 'status': 'completed'}, NOW)
    assert len(warnings) == 1 and 'stopped' in warnings[0]


def test_active_timer_does_not_hide_missed_run():
    warnings = health_warnings({'timer': 'active', 'result': 'success'},
        {'started_at': '2026-11-24T17:07:00Z', 'status': 'partial'}, NOW)
    assert len(warnings) == 1 and 'overdue' in warnings[0]


def test_manual_search_cannot_hide_missed_scheduled_search():
    warnings = health_warnings({'timer': 'active', 'scheduled_started': '2026-11-24T17:07:00Z'},
        {'started_at': NOW.isoformat(), 'status': 'completed'}, NOW)
    assert any('not recorded' in warning for warning in warnings)


def test_healthy_run_and_grace_period():
    assert not health_warnings({'timer': 'active'},
        {'started_at': '2026-11-27T09:07:00Z', 'status': 'completed'}, NOW)
    assert not health_warnings({'timer': 'active'},
        {'started_at': '2026-11-26T17:07:00Z', 'status': 'completed'},
        datetime.fromisoformat('2026-11-27T10:15:00+01:00'))


def test_failed_and_stuck_runs_are_reported():
    assert any('failed' in w for w in health_warnings(
        {'timer': 'active', 'result': 'exit-code'},
        {'started_at': NOW.isoformat(), 'status': 'failed'}, NOW))
    assert any('three hours' in w for w in health_warnings(
        {'timer': 'active'}, {'started_at': '2026-11-27T06:00:00Z', 'status': 'running'}, NOW))


def test_missing_history_is_not_healthy():
    assert any('verified' in w for w in health_warnings({'timer': 'active'}, None, NOW))


def test_unreachable_scheduler_is_unknown(monkeypatch):
    scheduler_state.clear()
    def unavailable(*args, **kwargs):
        raise subprocess.TimeoutExpired('systemctl', 3)
    monkeypatch.setattr('ui.discovery_health.subprocess.run', unavailable)
    assert scheduler_state() == {'timer': 'unknown'}
    scheduler_state.clear()


def test_timer_and_service_properties_parsed(monkeypatch):
    scheduler_state.clear()
    output = 'Id=pairrole-discovery.timer\nActiveState=active\n\nId=pairrole-discovery.service\nActiveState=inactive\nResult=success\nExecMainExitTimestamp=Fri 2026-11-27 10:12:00 CET\n'
    monkeypatch.setattr('ui.discovery_health.subprocess.run',
                        lambda *a, **kw: subprocess.CompletedProcess([], 0, output))
    assert scheduler_state()['timer'] == 'active'
    assert scheduler_state()['result'] == 'success'
    scheduler_state.clear()
