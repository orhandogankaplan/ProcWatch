"""Lag-free, dark-glass Tkinter dashboard with live CPU/RAM gauges and charts."""

from __future__ import annotations

import threading
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk
from typing import Deque, List, Optional

from procwatch import __version__
from procwatch.monitor import ProcessInfo, SystemSummary, get_system_summary, list_processes
from procwatch.profiles import DEFAULT_PROFILES, apply_profile, clean_idle_ram, safe_terminate


def _apply_dark_theme(root: tk.Tk | tk.Toplevel) -> None:
    root.configure(bg="#0b1120")
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background="#0b1120")
    style.configure("TLabel", background="#0b1120", foreground="#e2e8f0", font=("Segoe UI", 9))
    style.configure("Status.TLabel", background="#111827", foreground="#94a3b8", font=("Segoe UI", 8))

    style.configure(
        "TButton",
        background="#1e293b",
        foreground="#f8fafc",
        borderwidth=0,
        focusthickness=0,
        padding=(10, 5),
        font=("Segoe UI", 9),
    )
    style.map("TButton", background=[("active", "#334155")])

    style.configure(
        "Accent.TButton",
        background="#0284c7",
        foreground="#ffffff",
        borderwidth=0,
        padding=(10, 5),
        font=("Segoe UI", 9, "bold"),
    )
    style.map("Accent.TButton", background=[("active", "#0369a1")])

    style.configure("TCheckbutton", background="#0b1120", foreground="#cbd5e1", font=("Segoe UI", 9))
    style.map("TCheckbutton", background=[("active", "#0b1120")])

    style.configure(
        "TCombobox",
        fieldbackground="#1e293b",
        background="#1e293b",
        foreground="#f8fafc",
        arrowcolor="#38bdf8",
    )

    style.configure(
        "Treeview",
        background="#111827",
        foreground="#e2e8f0",
        fieldbackground="#111827",
        rowheight=26,
        borderwidth=0,
        font=("Segoe UI", 9),
    )
    style.configure(
        "Treeview.Heading",
        background="#1e293b",
        foreground="#38bdf8",
        relief="flat",
        font=("Segoe UI", 9, "bold"),
    )
    style.map("Treeview", background=[("selected", "#0369a1")], foreground=[("selected", "#ffffff")])


class ProcWatchApp:
    """Non-blocking, rich-telemetry process monitor and optimizer dashboard."""

    def __init__(self, root: tk.Tk | tk.Toplevel) -> None:
        self.root = root
        self.root.title(f"ProcWatch v{__version__} — Telemetry & Process Dashboard")
        self.root.geometry("900x620")
        self.root.minsize(740, 500)
        _apply_dark_theme(self.root)

        self.sort_var = tk.StringVar(value="memory")
        self.profile_var = tk.StringVar(value="gaming")
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready (standard user mode)")

        self.cpu_history: Deque[float] = deque([0.0] * 40, maxlen=40)
        self.ram_history: Deque[float] = deque([0.0] * 40, maxlen=40)
        self._fetching = False

        self._build_ui()
        self.trigger_refresh()
        self._schedule_refresh()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        self.telemetry = tk.Canvas(
            main,
            height=136,
            bg="#111827",
            highlightthickness=1,
            highlightbackground="#1e293b",
        )
        self.telemetry.pack(fill=tk.X, pady=(0, 10))
        self.telemetry.bind("<Configure>", lambda _e: self._draw_telemetry(None))
        self._last_summary: Optional[SystemSummary] = None

        ctrl_bar = ttk.Frame(main)
        ctrl_bar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(ctrl_bar, text="Sort:").pack(side=tk.LEFT)
        sort_box = ttk.Combobox(
            ctrl_bar,
            textvariable=self.sort_var,
            values=["memory", "cpu"],
            state="readonly",
            width=9,
        )
        sort_box.pack(side=tk.LEFT, padx=(4, 12))
        sort_box.bind("<<ComboboxSelected>>", lambda _e: self.trigger_refresh())

        ttk.Label(ctrl_bar, text="Profile:").pack(side=tk.LEFT)
        profile_box = ttk.Combobox(
            ctrl_bar,
            textvariable=self.profile_var,
            values=sorted(DEFAULT_PROFILES),
            state="readonly",
            width=9,
        )
        profile_box.pack(side=tk.LEFT, padx=(4, 6))

        ttk.Button(ctrl_bar, text="Preview", command=lambda: self._run_profile(dry_run=True)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(ctrl_bar, text="Apply", command=lambda: self._run_profile(dry_run=False)).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Button(
            ctrl_bar,
            text="Clean Idle RAM",
            style="Accent.TButton",
            command=self._clean_idle_ram,
        ).pack(side=tk.LEFT)

        ttk.Checkbutton(
            ctrl_bar,
            text="Auto (2.5s)",
            variable=self.auto_refresh_var,
        ).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(ctrl_bar, text="Refresh", command=self.trigger_refresh).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(ctrl_bar, text="Terminate", command=self._terminate_selected).pack(side=tk.RIGHT)

        table_frame = ttk.Frame(main)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("pid", "name", "memory_mb", "cpu_percent", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("pid", text="PID")
        self.tree.heading("name", text="Process Name")
        self.tree.heading("memory_mb", text="RAM (MB)")
        self.tree.heading("cpu_percent", text="CPU %")
        self.tree.heading("status", text="Status")

        self.tree.column("pid", width=80, anchor=tk.E)
        self.tree.column("name", width=330, anchor=tk.W)
        self.tree.column("memory_mb", width=120, anchor=tk.E)
        self.tree.column("cpu_percent", width=95, anchor=tk.E)
        self.tree.column("status", width=120, anchor=tk.W)

        self.tree.tag_configure("odd", background="#0f172a")
        self.tree.tag_configure("even", background="#162033")

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(main, textvariable=self.status_var, style="Status.TLabel", anchor=tk.W, padding=(8, 4)).pack(
            fill=tk.X, pady=(10, 0)
        )

    def _draw_telemetry(self, summary: Optional[SystemSummary]) -> None:
        if summary is not None:
            self._last_summary = summary
        s = self._last_summary
        w = max(640, self.telemetry.winfo_width())
        h = 136
        self.telemetry.delete("all")

        cpu_pct = s.cpu_percent if s else 0.0
        ram_pct = s.memory_percent if s else 0.0
        ram_text = f"{s.memory_used_gb}/{s.memory_total_gb} GB" if s else "-- / -- GB"
        proc_cnt = s.process_count if s else 0

        self._draw_gauge(68, 68, 42, cpu_pct, "#38bdf8", "CPU", f"{cpu_pct:.0f}%")
        self._draw_gauge(180, 68, 42, ram_pct, "#a855f7", "RAM", f"{ram_pct:.0f}%")

        chart_x0, chart_y0 = 250, 18
        chart_x1, chart_y1 = w - 18, h - 22
        cw = max(100, chart_x1 - chart_x0)
        ch = max(40, chart_y1 - chart_y0)

        for frac in (0.25, 0.5, 0.75, 1.0):
            gy = chart_y1 - frac * ch
            self.telemetry.create_line(chart_x0, gy, chart_x1, gy, fill="#1e293b", dash=(2, 3))

        self._draw_area_curve(self.ram_history, chart_x0, chart_y1, cw, ch, "#a855f7", "#2e1065")
        self._draw_area_curve(self.cpu_history, chart_x0, chart_y1, cw, ch, "#38bdf8", "#0c4a6e")

        self.telemetry.create_text(
            chart_x0, 10, anchor=tk.W,
            text=f"LIVE TELEMETRY   •   RAM {ram_text}   •   {proc_cnt} PROCESSES",
            fill="#94a3b8", font=("Segoe UI", 8, "bold"),
        )
        self.telemetry.create_text(
            chart_x1, 10, anchor=tk.E,
            text="● CPU    ● RAM",
            fill="#38bdf8", font=("Segoe UI", 8, "bold"),
        )

    def _draw_gauge(self, cx: int, cy: int, r: int, pct: float, color: str, label: str, val: str) -> None:
        self.telemetry.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#1e293b", width=6)
        extent = -max(3.0, (min(100.0, pct) / 100.0) * 359.0)
        self.telemetry.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=90, extent=extent, style=tk.ARC, outline=color, width=6,
        )
        self.telemetry.create_text(cx, cy - 6, text=val, fill="#f8fafc", font=("Segoe UI", 11, "bold"))
        self.telemetry.create_text(cx, cy + 12, text=label, fill="#94a3b8", font=("Segoe UI", 7, "bold"))

    def _draw_area_curve(
        self,
        data: Deque[float],
        x0: float,
        y_bottom: float,
        w: float,
        h: float,
        line_col: str,
        fill_col: str,
    ) -> None:
        pts: List[float] = []
        step = w / max(1, len(data) - 1)
        for idx, val in enumerate(data):
            px = x0 + idx * step
            py = y_bottom - (min(100.0, max(0.0, val)) / 100.0) * h
            pts.extend([px, py])
        if len(pts) >= 4:
            poly_pts = [x0, y_bottom, *pts, x0 + (len(data) - 1) * step, y_bottom]
            self.telemetry.create_polygon(poly_pts, fill=fill_col, stipple="gray25", outline="")
            self.telemetry.create_line(pts, fill=line_col, width=2.0, smooth=True)

    def trigger_refresh(self) -> None:
        if self._fetching or not self.root.winfo_exists():
            return
        self._fetching = True
        sort_by = self.sort_var.get()

        def _worker() -> None:
            try:
                # Accurate 400ms CPU measurement in background thread
                summary = get_system_summary(interval=0.4)
                procs = list_processes(sort_by=sort_by, limit=25)  # type: ignore[arg-type]
                if self.root.winfo_exists():
                    self.root.after(0, lambda: self._apply_snapshot(summary, procs))
            finally:
                self._fetching = False

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_snapshot(self, summary: SystemSummary, procs: List[ProcessInfo]) -> None:
        if not self.root.winfo_exists():
            return
        self.cpu_history.append(summary.cpu_percent)
        self.ram_history.append(summary.memory_percent)
        self._draw_telemetry(summary)

        selected_pid = None
        sel = self.tree.selection()
        if sel:
            selected_pid = self.tree.item(sel[0], "values")[0]

        for row in self.tree.get_children():
            self.tree.delete(row)

        for idx, proc in enumerate(procs):
            tag = "even" if idx % 2 == 0 else "odd"
            item_id = self.tree.insert(
                "",
                tk.END,
                values=(proc.pid, proc.name, f"{proc.memory_mb:.1f}", f"{proc.cpu_percent:.1f}", proc.status),
                tags=(tag,),
            )
            if selected_pid is not None and str(proc.pid) == str(selected_pid):
                self.tree.selection_set(item_id)

    def _schedule_refresh(self) -> None:
        if not self.root.winfo_exists():
            return
        if self.auto_refresh_var.get():
            self.trigger_refresh()
        self.root.after(2500, self._schedule_refresh)

    def _run_profile(self, dry_run: bool) -> None:
        profile = self.profile_var.get()
        items = apply_profile(profile, dry_run=dry_run)
        mode_label = "Preview" if dry_run else "Applied"
        if not items:
            msg = f"{mode_label} ({profile}): No matching background user processes found."
            self.status_var.set(msg)
            messagebox.showinfo("ProcWatch Profile", msg)
            return

        lines = [f"[{i.pid}] {i.name}: {i.detail}" for i in items[:12]]
        if len(items) > 12:
            lines.append(f"... and {len(items) - 12} more.")
        self.status_var.set(f"{mode_label} ({profile}): {len(items)} process(es) checked.")
        messagebox.showinfo(f"ProcWatch — {profile.title()} ({mode_label})", "\n".join(lines))

    def _clean_idle_ram(self) -> None:
        applied, freed_mb = clean_idle_ram(dry_run=False)
        done = sum(1 for item in applied if item.applied)
        if done == 0:
            self.status_var.set("No idle background RAM hogs found.")
        else:
            self.status_var.set(f"Cleaned {done} idle process(es), freeing ~{freed_mb:.1f} MB RAM.")
        self.trigger_refresh()

    def _terminate_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("ProcWatch", "Select a process from the table first.")
            return

        pid, name, *_ = self.tree.item(sel[0], "values")
        confirmed = messagebox.askyesno(
            "Confirm Termination",
            f"Safely terminate '{name}' (PID {pid})?",
        )
        if not confirmed:
            return

        items = safe_terminate(str(pid), force=False)
        if not items:
            self.status_var.set(f"Process {pid} no longer running.")
            self.trigger_refresh()
            return

        result = items[0]
        self.status_var.set(f"[{result.pid}] {result.name}: {result.detail}")
        if not result.applied:
            messagebox.showwarning("ProcWatch Safety", f"Action blocked: {result.detail}")
        self.trigger_refresh()


def launch_gui(master: Optional[tk.Misc] = None) -> int:
    """Launch the Tkinter desktop window."""
    if master is None:
        root = tk.Tk()
        ProcWatchApp(root)
        root.mainloop()
    else:
        win = tk.Toplevel(master)
        ProcWatchApp(win)
    return 0
