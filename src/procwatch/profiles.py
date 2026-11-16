"""Safe, user-scoped optimization profiles using OS process priority adjustments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List

import psutil

from procwatch.safety import get_current_username, is_owned_by_current_user, is_protected_process

# Default profiles target common heavy background apps without touching OS processes.
DEFAULT_PROFILES: Dict[str, Dict[str, List[str]]] = {
    "gaming": {
        "deprioritize": [
            "onedrive.exe",
            "dropbox.exe",
            "teams.exe",
            "ms-teams.exe",
            "slack.exe",
            "spotify.exe",
            "chrome.exe",
            "msedge.exe",
            "firefox.exe",
            "code.exe",
        ],
    },
    "work": {
        "deprioritize": [
            "steam.exe",
            "steamwebhelper.exe",
            "epicgameslauncher.exe",
            "discord.exe",
            "spotify.exe",
        ],
    },
    "battery": {
        "deprioritize": [
            "onedrive.exe",
            "dropbox.exe",
            "steam.exe",
            "epicgameslauncher.exe",
            "discord.exe",
            "spotify.exe",
            "chrome.exe",
            "msedge.exe",
        ],
    },
}


@dataclass(frozen=True)
class ActionItem:
    pid: int
    name: str
    action: str
    applied: bool
    detail: str


def _low_priority_value() -> int:
    if os.name == "nt":
        return getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
    return 10


def apply_profile(profile_name: str, dry_run: bool = True) -> List[ActionItem]:
    """Adjust priority of matching user-owned background processes for a profile."""
    key = profile_name.strip().lower()
    if key not in DEFAULT_PROFILES:
        valid = ", ".join(sorted(DEFAULT_PROFILES))
        raise ValueError(f"Unknown profile '{profile_name}'. Choose from: {valid}")

    targets = {name.lower() for name in DEFAULT_PROFILES[key]["deprioritize"]}
    current_user = get_current_username()
    low_prio = _low_priority_value()
    actions: List[ActionItem] = []

    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            pid = int(proc.info["pid"])
            name = proc.info.get("name") or ""
            if name.lower() not in targets:
                continue
            if is_protected_process(name, pid):
                continue
            if not is_owned_by_current_user(proc, current_user):
                continue

            if dry_run:
                actions.append(
                    ActionItem(
                        pid=pid,
                        name=name,
                        action="deprioritize",
                        applied=False,
                        detail="dry-run: would lower process priority",
                    )
                )
                continue

            proc.nice(low_prio)
            actions.append(
                ActionItem(
                    pid=pid,
                    name=name,
                    action="deprioritize",
                    applied=True,
                    detail="lowered process priority",
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            actions.append(
                ActionItem(
                    pid=proc.pid,
                    name=proc.info.get("name") or "unknown",
                    action="deprioritize",
                    applied=False,
                    detail=f"skipped ({exc.__class__.__name__})",
                )
            )

    return actions


def safe_terminate(pid_or_name: str, force: bool = False) -> List[ActionItem]:
    """Gracefully terminate user-owned, non-protected processes matching PID or name."""
    current_user = get_current_username()
    actions: List[ActionItem] = []
    is_pid = pid_or_name.isdigit()
    target_pid = int(pid_or_name) if is_pid else None
    target_name = pid_or_name.strip().lower()

    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            pid = int(proc.info["pid"])
            name = proc.info.get("name") or ""
            matched = (pid == target_pid) if is_pid else (name.lower() == target_name)
            if not matched:
                continue

            if is_protected_process(name, pid):
                actions.append(
                    ActionItem(
                        pid=pid,
                        name=name,
                        action="terminate",
                        applied=False,
                        detail="blocked: protected system process",
                    )
                )
                continue

            if not is_owned_by_current_user(proc, current_user):
                actions.append(
                    ActionItem(
                        pid=pid,
                        name=name,
                        action="terminate",
                        applied=False,
                        detail="blocked: not owned by current user",
                    )
                )
                continue

            if force:
                proc.kill()
            else:
                proc.terminate()
            actions.append(
                ActionItem(
                    pid=pid,
                    name=name,
                    action="kill" if force else "terminate",
                    applied=True,
                    detail="signal sent",
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            actions.append(
                ActionItem(
                    pid=proc.pid,
                    name=proc.info.get("name") or "unknown",
                    action="terminate",
                    applied=False,
                    detail=f"failed ({exc.__class__.__name__})",
                )
            )

    return actions
