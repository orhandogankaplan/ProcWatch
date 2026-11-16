# ProcWatch

A lightweight, open-source process monitor and resource optimizer designed to stay strictly within standard user permissions on Windows and Linux—no admin elevation required, no kernel drivers, and no unsafe memory injection.

## Why ProcWatch?

Many "RAM booster" utilities trigger antivirus false positives or UAC prompts because they attempt to trim system working sets or inject into elevated processes. ProcWatch takes a transparent, security-first approach:

- **Standard User Scope (`asInvoker`)**: Only inspects and manages processes owned by the current user.
- **Protected Process Guardrails**: Hardcoded allowlist/blocklist prevents touching critical OS, security, and shell processes (`System`, `lsass.exe`, `MsMpEng.exe`, `explorer.exe`, `systemd`, etc.).
- **Safe Optimization via OS Priority**: Uses standard priority adjustments (`BELOW_NORMAL_PRIORITY_CLASS` on Windows, `nice` on Linux/macOS) and graceful termination instead of intrusive memory manipulation.
- **Dry-Run by Default**: `procwatch optimize` previews every action before applying changes unless `--apply` is explicitly passed.

## Installation

```bash
pip install -e .
```

For development and testing:

```bash
pip install -e ".[dev]"
pytest
```

## Usage

```bash
# Show overall CPU and RAM summary
procwatch status

# List top 15 memory-consuming user processes
procwatch top --sort memory --limit 15

# Preview what the gaming profile would adjust (safe dry-run)
procwatch optimize --profile gaming

# Apply the gaming profile
procwatch optimize --profile gaming --apply

# Safely terminate a user-owned process by PID or name
procwatch terminate 12345
```

## Windows Packaging Notes

To minimize Windows Defender SmartScreen and false-positive warnings when building an executable:

1. Use PyInstaller `--onedir` mode wrapped in an installer (e.g., Inno Setup) rather than `--onefile`.
2. Sign releases with a trusted certificate (such as SignPath for open-source projects).
3. Keep the application manifest at `asInvoker` so Windows does not prompt for UAC elevation.

## License

MIT
