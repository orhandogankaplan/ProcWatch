"""Unit tests for ProcWatch."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from procwatch.cli import build_parser, main
from procwatch.monitor import get_system_summary, list_processes
from procwatch.profiles import apply_profile, safe_terminate
from procwatch.safety import is_owned_by_current_user, is_protected_process


def test_protected_processes():
    assert is_protected_process("svchost.exe", 1000) is True
    assert is_protected_process("MsMpEng.exe", 2000) is True
    assert is_protected_process("python.exe", 4) is True
    assert is_protected_process("python.exe", os.getpid()) is True
    assert is_protected_process("notepad.exe", 99999) is False


def test_is_owned_by_current_user():
    proc = MagicMock()
    proc.username.return_value = "DESKTOP-PC\\orhan"
    assert is_owned_by_current_user(proc, current_user="orhan") is True
    assert is_owned_by_current_user(proc, current_user="SYSTEM") is False


def test_system_summary():
    summary = get_system_summary()
    assert summary.memory_total_gb > 0
    assert 0 <= summary.memory_percent <= 100
    assert summary.process_count > 0


def test_list_processes_filters_protected():
    p1 = MagicMock()
    p1.info = {
        "pid": 500,
        "name": "svchost.exe",
        "username": "orhan",
        "cpu_percent": 1.0,
        "memory_info": SimpleNamespace(rss=50 * 1024 * 1024),
        "memory_percent": 1.0,
        "status": "running",
    }
    p2 = MagicMock()
    p2.info = {
        "pid": 99999,
        "name": "my_app.exe",
        "username": "orhan",
        "cpu_percent": 5.0,
        "memory_info": SimpleNamespace(rss=120 * 1024 * 1024),
        "memory_percent": 2.5,
        "status": "running",
    }
    p2.username.return_value = "orhan"

    with patch("procwatch.monitor.get_current_username", return_value="orhan"), patch(
        "procwatch.monitor.psutil.process_iter", return_value=[p1, p2]
    ):
        procs = list_processes(limit=10)
        assert len(procs) == 1
        assert procs[0].name == "my_app.exe"
        assert procs[0].memory_mb == 120.0


def test_apply_profile_dry_run():
    proc = MagicMock()
    proc.pid = 88888
    proc.info = {"pid": 88888, "name": "spotify.exe"}
    proc.username.return_value = "orhan"

    with patch("procwatch.profiles.get_current_username", return_value="orhan"), patch(
        "procwatch.profiles.psutil.process_iter", return_value=[proc]
    ):
        actions = apply_profile("gaming", dry_run=True)
        assert len(actions) == 1
        assert actions[0].applied is False
        assert "dry-run" in actions[0].detail
        proc.nice.assert_not_called()


def test_safe_terminate_blocks_protected():
    proc = MagicMock()
    proc.pid = 777
    proc.info = {"pid": 777, "name": "lsass.exe"}

    with patch("procwatch.profiles.get_current_username", return_value="orhan"), patch(
        "procwatch.profiles.psutil.process_iter", return_value=[proc]
    ):
        actions = safe_terminate("lsass.exe")
        assert len(actions) == 1
        assert actions[0].applied is False
        assert "protected" in actions[0].detail
        proc.terminate.assert_not_called()


def test_cli_parser_and_status(capsys):
    parser = build_parser()
    args = parser.parse_args(["optimize", "--profile", "work"])
    assert args.profile == "work"
    assert args.apply is False

    rc = main(["status"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "CPU:" in captured.out
