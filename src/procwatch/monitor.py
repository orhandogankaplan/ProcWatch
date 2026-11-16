"""Process monitoring and system resource summary utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

import psutil

from procwatch.safety import get_current_username, is_owned_by_current_user, is_protected_process

SortField = Literal["memory", "cpu"]


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    username: str
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    status: str
    protected: bool


@dataclass(frozen=True)
class SystemSummary:
    cpu_percent: float
    memory_total_gb: float
    memory_used_gb: float
    memory_percent: float
    process_count: int


def get_system_summary() -> SystemSummary:
    """Return a snapshot of overall CPU and memory usage."""
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    return SystemSummary(
        cpu_percent=round(cpu, 1),
        memory_total_gb=round(vm.total / (1024**3), 2),
        memory_used_gb=round(vm.used / (1024**3), 2),
        memory_percent=round(vm.percent, 1),
        process_count=len(psutil.pids()),
    )


def list_processes(
    sort_by: SortField = "memory",
    limit: int = 15,
    include_protected: bool = False,
    only_current_user: bool = True,
) -> List[ProcessInfo]:
    """List running processes sorted by memory or CPU usage."""
    current_user = get_current_username()
    results: List[ProcessInfo] = []

    attrs = ["pid", "name", "username", "cpu_percent", "memory_info", "memory_percent", "status"]
    for proc in psutil.process_iter(attrs=attrs):
        try:
            info = proc.info
            pid = int(info["pid"])
            name = info.get("name") or "unknown"
            protected = is_protected_process(name, pid)

            if protected and not include_protected:
                continue
            if only_current_user and not is_owned_by_current_user(proc, current_user):
                continue

            mem_info = info.get("memory_info")
            mem_mb = round(mem_info.rss / (1024**2), 1) if mem_info else 0.0
            mem_pct = round(float(info.get("memory_percent") or 0.0), 2)
            cpu_pct = round(float(info.get("cpu_percent") or 0.0), 1)

            results.append(
                ProcessInfo(
                    pid=pid,
                    name=name,
                    username=info.get("username") or "",
                    cpu_percent=cpu_pct,
                    memory_mb=mem_mb,
                    memory_percent=mem_pct,
                    status=info.get("status") or "unknown",
                    protected=protected,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    key_fn = (lambda p: p.cpu_percent) if sort_by == "cpu" else (lambda p: p.memory_mb)
    results.sort(key=key_fn, reverse=True)
    return results[: max(1, limit)]
