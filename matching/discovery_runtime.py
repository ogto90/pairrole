"""Resolve the installed Bun runtime for shell and desktop-launched discovery."""
import os
from pathlib import Path
import shutil


def bun_command() -> str:
    # Desktop launchers need not inherit the user's interactive shell PATH.
    command = shutil.which('bun')
    if command:
        return command
    installed = Path.home() / '.bun' / 'bin' / 'bun'
    if installed.is_file() and os.access(installed, os.X_OK):
        return str(installed)
    raise RuntimeError('Bun is not installed or executable. Install Bun before starting discovery.')
