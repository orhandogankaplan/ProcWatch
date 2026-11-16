"""Command-line interface and interactive menu for ProcWatch."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from procwatch import __version__
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


def _print_status() -> None:
    s = get_system_summary()
    print(
        f"CPU: {s.cpu_percent}% | RAM: {s.memory_used_gb}/{s.memory_total_gb} GB "
        f"({s.memory_percent}%) | Processes: {s.process_count}"
    )


def _print_top(sort_by: str = "memory", limit: int = 15, include_protected: bool = False) -> None:
    procs = list_processes(
        sort_by=sort_by,  # type: ignore[arg-type]
        limit=limit,
        include_protected=include_protected,
    )
    print(f"{'PID':>7}  {'NAME':<26} {'MEM (MB)':>9}  {'CPU %':>6}  {'STATUS'}")
    for p in procs:
        print(f"{p.pid:>7}  {p.name[:26]:<26} {p.memory_mb:>9.1f}  {p.cpu_percent:>6.1f}  {p.status}")


def _run_optimize(profile: str, dry_run: bool) -> None:
    items = apply_profile(profile, dry_run=dry_run)
    if not items:
        print(f"No matching background user processes found for profile '{profile}'.")
        return
    for item in items:
        print(f"[{item.pid}] {item.name}: {item.action} -> {item.detail}")


def _prompt_profile() -> str | None:
    names = sorted(DEFAULT_PROFILES)
    print(f"Available profiles: {', '.join(names)}")
    choice = input("Enter profile name: ").strip().lower()
    if choice not in DEFAULT_PROFILES:
        print(f"Invalid profile '{choice}'.")
        return None
    return choice


def interactive_menu() -> int:
    """Keep console open with an interactive menu when launched without arguments."""
    print(f"=== ProcWatch v{__version__} (Safe User-Scoped Mode) ===")
    while True:
        print("\nChoose an action:")
        print("  1) System status (CPU / RAM)")
        print("  2) Top 15 processes by RAM")
        print("  3) Top 15 processes by CPU")
        print("  4) Preview optimization profile (dry-run)")
        print("  5) Apply optimization profile")
        print("  6) Safely terminate a user process")
        print("  0) Exit")

        try:
            choice = input("\nSelect [0-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting ProcWatch.")
            return 0

        print()
        if choice == "1":
            _print_status()
        elif choice == "2":
            _print_top(sort_by="memory", limit=15)
        elif choice == "3":
            _print_top(sort_by="cpu", limit=15)
        elif choice == "4":
            profile = _prompt_profile()
            if profile:
                _run_optimize(profile, dry_run=True)
        elif choice == "5":
            profile = _prompt_profile()
            if profile:
                _run_optimize(profile, dry_run=False)
        elif choice == "6":
            target = input("Enter PID or process name (e.g. notepad.exe): ").strip()
            if not target:
                print("Cancelled.")
                continue
            items = safe_terminate(target, force=False)
            if not items:
                print(f"No matching process found for '{target}'.")
            else:
                for item in items:
                    print(f"[{item.pid}] {item.name}: {item.action} -> {item.detail}")
        elif choice == "0":
            print("Goodbye.")
            return 0
        else:
            print("Invalid selection. Enter a number from 0 to 6.")


def main(argv: Sequence[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:]) if argv is None else list(argv)
    if not effective_argv:
        return interactive_menu()

    parser = build_parser()
    args = parser.parse_args(effective_argv)

    if args.command == "status":
        _print_status()
        return 0

    if args.command == "top":
        _print_top(
            sort_by=args.sort,
            limit=args.limit,
            include_protected=args.include_protected,
        )
        return 0

    if args.command == "optimize":
        _run_optimize(args.profile, dry_run=not args.apply)
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