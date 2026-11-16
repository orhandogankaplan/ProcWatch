"""Safe, user-scoped optimization profiles and idle RAM cleanup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

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

# Known background apps that commonly hold substantial RAM while idle.
IDLE_CLEAN_TARGETS: frozenset[str] = frozenset(
    {
        "onedrive.exe",
        "dropbox.exe",
        "teams.exe",
        "ms-teams.exe",
        "slack.exe",
        "spotify.exe",
        "discord.exe",
        "steam.exe",
        "steamwebhelper.exe",
        "epicgameslauncher.exe",
        "ccxprocess.exe",
        "adobeipcbroker.exe",
        "cortana.exe",
        "yourphone.exe",
        "phoneexperiencehost.exe",
    }
)


@dataclass(frozen=True)
class ActionItem:
    pid: int
    name: str
    action: str
    applied: bool
    detail: str
    memory_mb: float = 0.0


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


def clean_idle_ram(
    min_ram_mb: float = 80.0,
    max_cpu_percent: float = 2.0,
    dry_run: bool = True,
) -> Tuple[List[ActionItem], float]:
    """Safely terminate idle background RAM-hogging apps owned by the current user."""
    current_user = get_current_username()
    actions: List[ActionItem] = []
    freed_mb = 0.0

    attrs = ["pid", "name", "cpu_percent", "memory_info"]
    for proc in psutil.process_iter(attrs=attrs):
        try:
            pid = int(proc.info["pid"])
            name = proc.info.get("name") or ""
            if name.lower() not in IDLE_CLEAN_TARGETS:
                continue
            if is_protected_process(name, pid):
                continue
            if not is_owned_by_current_user(proc, current_user):
                continue

            mem_info = proc.info.get("memory_info")
            mem_mb = round(mem_info.rss / (1024**2), 1) if mem_info else 0.0
            cpu_pct = float(proc.info.get("cpu_percent") or 0.0)

            if mem_mb < min_ram_mb or cpu_pct > max_cpu_percent:
                continue

            if dry_run:
                freed_mb += mem_mb
                actions.append(
                    ActionItem(
                        pid=pid,
                        name=name,
                        action="clean-ram",
                        applied=False,
                        detail=f"dry-run: idle ({mem_mb:.1f} MB)",
                        memory_mb=mem_mb,
                    )
                )
                continue

            proc.terminate()
            freed_mb += mem_mb
            actions.append(
                ActionItem(
                    pid=pid,
                    name=name,
                    action="clean-ram",
                    applied=True,
                    detail=f"terminated idle app ({mem_mb:.1f} MB freed)",
                    memory_mb=mem_mb,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            actions.append(
                ActionItem(
                    pid=proc.pid,
                    name=proc.info.get("name") or "unknown",
                    action="clean-ram",
                    applied=False,
                    detail=f"skipped ({exc.__class__.__name__})",
                )
            )

    return actions, round(freed_mb, 1)


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
