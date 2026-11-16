"""Command-line interface for ProcWatch."""

from __future__ import annotations

import argparse
from typing import Sequence

from procwatch.monitor import get_system_summary, list_processes
from procwatch.profiles import DEFAULT_PROFILES, apply_profile, safe_terminate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="procwatch",
        description="Safe, user-scoped process monitor and resource optimizer.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show overall CPU and RAM usage.")

    top_p = sub.add_parser("top", help="List top resource-consuming user processes.")
    top_p.add_argument("--sort", choices=["memory", "cpu"], default="memory")
    top_p.add_argument("--limit", type=int, default=15)
    top_p.add_argument("--include-protected", action="store_true")

    opt_p = sub.add_parser("optimize", help="Apply or preview an optimization profile.")
    opt_p.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), required=True)
    opt_p.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply priority changes (defaults to safe dry-run).",
    )

    term_p = sub.add_parser("terminate", help="Safely terminate a user-owned process.")
    term_p.add_argument("target", help="PID or exact process name (e.g. notepad.exe).")
    term_p.add_argument("--force", action="store_true", help="Use SIGKILL / hard kill.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        s = get_system_summary()
        print(
            f"CPU: {s.cpu_percent}% | RAM: {s.memory_used_gb}/{s.memory_total_gb} GB "
            f"({s.memory_percent}%) | Processes: {s.process_count}"
        )
        return 0

    if args.command == "top":
        procs = list_processes(
            sort_by=args.sort,
            limit=args.limit,
            include_protected=args.include_protected,
        )
        print(f"{'PID':>7}  {'NAME':<26} {'MEM (MB)':>9}  {'CPU %':>6}  {'STATUS'}")
        for p in procs:
            print(f"{p.pid:>7}  {p.name[:26]:<26} {p.memory_mb:>9.1f}  {p.cpu_percent:>6.1f}  {p.status}")
        return 0

    if args.command == "optimize":
        dry_run = not args.apply
        items = apply_profile(args.profile, dry_run=dry_run)
        if not items:
            print(f"No matching background user processes found for profile '{args.profile}'.")
            return 0
        for item in items:
            print(f"[{item.pid}] {item.name}: {item.action} -> {item.detail}")
        return 0

    if args.command == "terminate":
        items = safe_terminate(args.target, force=args.force)
        if not items:
            print(f"No matching process found for '{args.target}'.")
            return 1
        for item in items:
            print(f"[{item.pid}] {item.name}: {item.action} -> {item.detail}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
