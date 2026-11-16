"""Minimal dark-glass desktop CPU & RAM widget with automatic idle RAM cleaner."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import tkinter as tk
from typing import Callable, Optional

import psutil

from procwatch import __version__
from procwatch.profiles import clean_idle_ram

_BG = "#0b1528"
_BORDER = "#1e3050"
_TRACK = "#1e293b"
_CPU_COLOR = "#2dd4bf"
_RAM_COLOR = "#a78bfa"


def _apply_win11_rounded_corners(win: tk.Tk | tk.Toplevel) -> None:
    """Use native Windows 11 DWM rounded corners without chroma-key lag."""
    if os.name != "nt":
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)
        )
    except Exception:
        pass


class CpuWidget3D:
    """Minimal desktop CPU & RAM card with continuous background idle RAM cleanup."""

    def __init__(
        self,
        master: Optional[tk.Misc] = None,
        on_open_dashboard: Optional[Callable[[], None]] = None,
    ) -> None:
        self.win: tk.Tk | tk.Toplevel = tk.Tk() if master is None else tk.Toplevel(master)
        self.on_open_dashboard = on_open_dashboard
        self._topmost = False
        self._auto_clean = True
        self._cleaning = False

        self.win.title(f"ProcWatch v{__version__}")
        self.win.overrideredirect(True)
        self.win.configure(bg=_BG)
        try:
            self.win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        w, h = 250, 152
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{max(24, sw - w - 32)}+{max(24, sh - h - 72)}")
        _apply_win11_rounded_corners(self.win)

        self._drag_x = 0
        self._drag_y = 0
        self.cpu_pct = 0.0
        self.ram_pct = 0.0
        self.ram_used_gb = 0.0
        self.ram_total_gb = 0.0
        self._prev_cpu_times = psutil.cpu_times()
        self._flash_msg = ""
        self._flash_until = 0
        self._tick_count = 0

        self.canvas = tk.Canvas(
            self.win,
            width=w,
            height=h,
            bg=_BG,
            highlightthickness=1,
            highlightbackground=_BORDER,
            bd=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.create_text(
            18, 18, anchor=tk.W, text="CPU", fill="#94a3b8", font=("Segoe UI", 8, "bold")
        )
        self._cpu_big = self.canvas.create_text(
            18, 40, anchor=tk.W, text="0%", fill="#f8fafc", font=("Segoe UI", 17, "bold")
        )
        self._cpu_sub = self.canvas.create_text(
            232, 43, anchor=tk.E, text="0 / 100", fill="#cbd5e1", font=("Segoe UI", 9)
        )
        self._draw_pill_track(18, 59, 232, 65)
        self._cpu_bar = self._create_pill_fill(18, 59, 24, 65, _CPU_COLOR)

        self.canvas.create_text(
            18, 82, anchor=tk.W, text="RAM", fill="#94a3b8", font=("Segoe UI", 8, "bold")
        )
        self._ram_big = self.canvas.create_text(
            18, 104, anchor=tk.W, text="0%", fill="#f8fafc", font=("Segoe UI", 17, "bold")
        )
        self._ram_sub = self.canvas.create_text(
            232, 107, anchor=tk.E, text="0.0 / 0.0 GB", fill="#cbd5e1", font=("Segoe UI", 9)
        )
        self._draw_pill_track(18, 123, 232, 129)
        self._ram_bar = self._create_pill_fill(18, 123, 24, 129, _RAM_COLOR)

        self._footer = self.canvas.create_text(
            18, 141, anchor=tk.W, text="Auto-Clean: ON", fill="#475569", font=("Segoe UI", 7)
        )

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Double-Button-1>", lambda _e: self._handle_dashboard())

        self.menu = tk.Menu(self.win, tearoff=0)
        self.menu.add_command(label="Clean Idle RAM Now", command=self._trigger_clean_ram)
        self.menu.add_command(label="Auto-Clean RAM: ON/OFF", command=self._toggle_auto_clean)
        self.menu.add_separator()
        self.menu.add_command(label="Open Dashboard", command=self._handle_dashboard)
        self.menu.add_command(label="Toggle Always on Top", command=self._toggle_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="Close", command=self.close)
        self.canvas.bind("<Button-3>", self._show_menu)

        self._update_loop()

    def _draw_pill_track(self, x1: float, y1: float, x2: float, y2: float) -> None:
        r = (y2 - y1) / 2.0
        self.canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=_TRACK, outline="")
        self.canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=_TRACK, outline="")
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=_TRACK, outline="")

    def _create_pill_fill(self, x1: float, y1: float, x2: float, y2: float, color: str) -> tuple[int, int, int]:
        r = (y2 - y1) / 2.0
        c1 = self.canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=color, outline="")
        c2 = self.canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=color, outline="")
        rect = self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="")
        return (c1, rect, c2)

    def _set_pill_fill(self, items: tuple[int, int, int], pct: float, y1: float, y2: float) -> None:
        x1, max_x2 = 18.0, 232.0
        r = (y2 - y1) / 2.0
        span = max_x2 - x1
        fill_w = max(2 * r, (min(100.0, max(0.0, pct)) / 100.0) * span)
        x2 = x1 + fill_w
        c1, rect, c2 = items
        self.canvas.coords(c1, x1, y1, x1 + 2 * r, y2)
        self.canvas.coords(c2, x2 - 2 * r, y1, x2, y2)
        self.canvas.coords(rect, x1 + r, y1, x2 - r, y2)

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event: tk.Event) -> None:
        x = self.win.winfo_x() + (event.x - self._drag_x)
        y = self.win.winfo_y() + (event.y - self._drag_y)
        self.win.geometry(f"+{x}+{y}")

    def _show_menu(self, event: tk.Event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def _toggle_topmost(self) -> None:
        self._topmost = not self._topmost
        self.win.attributes("-topmost", self._topmost)

    def _toggle_auto_clean(self) -> None:
        self._auto_clean = not self._auto_clean
        self._refresh_footer()

    def _sample_metrics(self) -> None:
        now = psutil.cpu_times()
        prev = self._prev_cpu_times
        total_delta = sum(now) - sum(prev)
        idle_delta = now.idle - prev.idle
        if total_delta > 0:
            self.cpu_pct = max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))
        self._prev_cpu_times = now

        vm = psutil.virtual_memory()
        self.ram_pct = vm.percent
        self.ram_used_gb = vm.used / (1024**3)
        self.ram_total_gb = vm.total / (1024**3)

    def _refresh_footer(self) -> None:
        if self._flash_until > self._tick_count:
            self.canvas.itemconfigure(self._footer, text=self._flash_msg, fill="#34d399")
        else:
            state = "ON" if self._auto_clean else "OFF"
            self.canvas.itemconfigure(self._footer, text=f"Auto-Clean: {state}", fill="#475569")

    def _update_loop(self) -> None:
        if not self.win.winfo_exists():
            return

        self._tick_count += 1
        self._sample_metrics()

        cpu_int = int(round(self.cpu_pct))
        ram_int = int(round(self.ram_pct))

        self.canvas.itemconfigure(self._cpu_big, text=f"{cpu_int}%")
        self.canvas.itemconfigure(self._cpu_sub, text=f"{cpu_int} / 100")
        self._set_pill_fill(self._cpu_bar, self.cpu_pct, 59, 65)

        self.canvas.itemconfigure(self._ram_big, text=f"{ram_int}%")
        self.canvas.itemconfigure(
            self._ram_sub, text=f"{self.ram_used_gb:.1f} / {self.ram_total_gb:.0f} GB"
        )
        self._set_pill_fill(self._ram_bar, self.ram_pct, 123, 129)

        if self._auto_clean and (self._tick_count == 3 or self._tick_count % 30 == 0):
            self._trigger_clean_ram(silent_if_none=True)

        self._refresh_footer()
        self.win.after(1000, self._update_loop)

    def _trigger_clean_ram(self, silent_if_none: bool = False) -> None:
        if self._cleaning:
            return
        self._cleaning = True

        def _worker() -> None:
            try:
                applied, freed_mb = clean_idle_ram(dry_run=False)
                done = sum(1 for item in applied if item.applied)
                if self.win.winfo_exists():
                    self.win.after(0, lambda: self._on_clean_done(done, freed_mb, silent_if_none))
            finally:
                self._cleaning = False

        threading.Thread(target=_worker, daemon=True).start()

    def _on_clean_done(self, done: int, freed_mb: float, silent_if_none: bool) -> None:
        if not self.win.winfo_exists():
            return
        if done > 0:
            self._flash_msg = f"Auto-Cleaned ~{freed_mb:.0f} MB ({done} app)"
            self._flash_until = self._tick_count + 5
        elif not silent_if_none:
            self._flash_msg = "RAM Clean — no idle apps"
            self._flash_until = self._tick_count + 4
        self._refresh_footer()

    def _handle_dashboard(self) -> None:
        if self.on_open_dashboard is not None:
            self.on_open_dashboard()
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable, "gui"], creationflags=flags)
        else:
            subprocess.Popen([sys.executable, "-m", "procwatch.cli", "gui"], creationflags=flags)

    def close(self) -> None:
        self.win.destroy()


def launch_widget_3d() -> int:
    """Launch the minimal desktop CPU & RAM widget."""
    widget = CpuWidget3D()
    widget.win.mainloop()
    return 0
