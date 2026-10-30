"""Cheevos inside PyUI's process: open, close and open again, then nothing of it is left."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PYUI_DIR = Path(os.environ.get("CHEEVOS_PYUI_DIR", REPO / ".spruceos/App/PyUI/main-ui"))
DRIVER = Path(__file__).with_name("native_session.py")

pytestmark = [
    pytest.mark.screens,
    pytest.mark.skipif(not (PYUI_DIR / "mainui.py").is_file(), reason="no PyUI checkout"),
]


def run_sessions(tmp_path: Path, script: str, *extra: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            str(tmp_path / "sd"),
            str(tmp_path / "shots"),
            script,
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_two_sessions_leave_nothing_behind(tmp_path):
    # Home, Games, a game (its details load on a worker), back out; then Home again and out.
    report = run_sessions(tmp_path, "down,a,wait:6,a,wait:12,b,b,b,shot:again,b")
    assert report == {"unplayed": [], "modules": [], "objects": [], "hooks": [], "threads": []}
    assert (tmp_path / "shots" / "640x480" / "again.png").is_file()


def test_a_game_only_session_leaves_nothing_behind(tmp_path):
    report = run_sessions(tmp_path, "b,wait:12,b", "519")
    assert report == {"unplayed": [], "modules": [], "objects": [], "hooks": [], "threads": []}
