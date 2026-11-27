import os
from pathlib import Path
from unittest.mock import patch
import pytest

from matching.discovery_runtime import bun_command


def test_desktop_path_finds_user_install(monkeypatch, tmp_path):
    monkeypatch.setattr('matching.discovery_runtime.shutil.which', lambda _: None)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    installed = tmp_path / '.bun/bin/bun'
    installed.parent.mkdir(parents=True)
    installed.write_text('#!/bin/sh\n')
    installed.chmod(0o755)
    assert bun_command() == str(installed)


def test_missing_runtime_rejects_bundled_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr('matching.discovery_runtime.shutil.which', lambda _: None)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    with pytest.raises(RuntimeError, match='Bun'):
        bun_command()


def test_spawn_failure_does_not_leave_running_status(monkeypatch, tmp_path):
    import ui.discovery_runner as runner
    monkeypatch.setattr(runner, 'STATUS_FILE', tmp_path / 'status.json')
    monkeypatch.setattr(runner, '_bun_command', lambda: '/opt/bun/bin/bun')
    with patch.object(runner.subprocess, 'Popen', side_effect=OSError('failed')):
        with pytest.raises(RuntimeError, match='Could not launch'):
            runner.start_discovery(user_id='test-user')
    assert runner.read_discovery_status(runner.STATUS_FILE)['status'] == 'failed'
