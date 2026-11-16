"""Safety guardrails to prevent touching OS, security, or elevated processes."""

from __future__ import annotations

import getpass
import os
from typing import Optional

import psutil

# Critical Windows, Linux, and macOS processes that must never be modified or terminated.
PROTECTED_PROCESS_NAMES: frozenset[str] = frozenset(
    {
        # Windows core & security
        "system",
        "system idle process",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "lsm.exe",
        "svchost.exe",
        "winlogon.exe",
        "dwm.exe",
        "explorer.exe",
        "taskmgr.exe",
        "msmpeng.exe",
        "nissrv.exe",
        "securityhealthservice.exe",
        "sgrmbroker.exe",
        "audiodg.exe",
        "fontdrvhost.exe",
        "sihost.exe",
        "ctfmon.exe",
        "searchindexer.exe",
        # Linux / macOS core
        "init",
        "systemd",
        "kthreadd",
        "launchd",
        "kernel_task",
        "sshd",
        "dbus-daemon",
        "networkmanager",
    }
)


def get_current_username() -> str:
    """Return the normalized current OS username."""
    try:
        return getpass.getuser().lower()
    except Exception:
        return ""


def _normalize_username(username: Optional[str]) -> str:
    if not username:
        return ""
    # Handle Windows DOMAIN\User format
    if "\\" in username:
        username = username.split("\\", 1)[1]
    return username.strip().lower()


def is_protected_process(name: str, pid: int) -> bool:
    """Return True if the process is critical to the OS or is ProcWatch itself."""
    if pid <= 4:
        return True
    if pid == os.getpid() or pid == os.getppid():
        return True
    return name.strip().lower() in PROTECTED_PROCESS_NAMES


def is_owned_by_current_user(proc: psutil.Process, current_user: Optional[str] = None) -> bool:
    """Return True only when the process belongs to the current user."""
    target_user = (current_user or get_current_username()).lower()
    if not target_user:
        return False
    try:
        proc_user = _normalize_username(proc.username())
        return proc_user == target_user
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
