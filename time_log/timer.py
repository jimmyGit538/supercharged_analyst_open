"""
Hotkey timer with GUI — press Ctrl+Shift+T or click Start/Stop.
Logs time entries with descriptions to logged_time.csv.
"""

import csv
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont

import keyboard  # pip install keyboard

HOTKEY = "ctrl+shift+home"
CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logged_time.csv")
CSV_HEADERS = ["Description", "Start Time", "End Time", "Duration"]

# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_HEADERS)


def append_csv(description, start_dt, end_dt, duration_str):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            description,
            start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            duration_str,
        ])


def load_csv_rows():
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_elapsed(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class TimerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Supercharged Timer")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e2e")

        self._running = False
        self._start_time: float | None = None
        self._start_dt: datetime | None = None
        self._lock = threading.Lock()

        ensure_csv()
        self._build_ui()
        self._tick()

        # Global hotkey — runs on a background thread, schedule onto main thread
        keyboard.add_hotkey(HOTKEY, lambda: self.root.after(0, self._toggle))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        PAD = 16
        BG = "#1e1e2e"
        SURFACE = "#2a2a3e"
        ACCENT = "#89b4fa"
        TEXT = "#cdd6f4"
        SUBTLE = "#6c7086"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"

        self._colors = dict(bg=BG, surface=SURFACE, accent=ACCENT,
                            text=TEXT, subtle=SUBTLE, green=GREEN, red=RED)

        # ── Timer display ────────────────────────────────────────────
        timer_frame = tk.Frame(self.root, bg=SURFACE, padx=PAD * 2, pady=PAD)
        timer_frame.pack(fill="x", padx=PAD, pady=(PAD, 0))

        big_font = tkfont.Font(family="Consolas", size=48, weight="bold")
        self._timer_label = tk.Label(
            timer_frame, text="00:00", font=big_font,
            fg=ACCENT, bg=SURFACE, width=8,
        )
        self._timer_label.pack()

        self._status_label = tk.Label(
            timer_frame, text="Stopped", font=("Segoe UI", 11),
            fg=SUBTLE, bg=SURFACE,
        )
        self._status_label.pack()

        # ── Description entry ────────────────────────────────────────
        desc_frame = tk.Frame(self.root, bg=BG, padx=PAD, pady=8)
        desc_frame.pack(fill="x", padx=PAD)

        tk.Label(desc_frame, text="Description", font=("Segoe UI", 10),
                 fg=SUBTLE, bg=BG).pack(anchor="w")

        self._desc_var = tk.StringVar()
        self._desc_entry = tk.Entry(
            desc_frame, textvariable=self._desc_var,
            font=("Segoe UI", 12), bg=SURFACE, fg=TEXT,
            insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightcolor=ACCENT,
            highlightbackground=SUBTLE,
        )
        self._desc_entry.pack(fill="x", ipady=6)

        # ── Buttons ──────────────────────────────────────────────────
        btn_frame = tk.Frame(self.root, bg=BG, padx=PAD, pady=4)
        btn_frame.pack(fill="x", padx=PAD)

        self._toggle_btn = tk.Button(
            btn_frame, text="▶  Start",
            font=("Segoe UI", 11, "bold"),
            bg=GREEN, fg="#1e1e2e", activebackground=GREEN,
            relief="flat", cursor="hand2", padx=16, pady=8,
            command=self._toggle,
        )
        self._toggle_btn.pack(side="left")

        tk.Label(btn_frame, text=f"  hotkey: {HOTKEY.upper()}",
                 font=("Segoe UI", 9), fg=SUBTLE, bg=BG).pack(side="left", padx=8)

        # ── Log table ────────────────────────────────────────────────
        log_outer = tk.Frame(self.root, bg=BG)
        log_outer.pack(fill="both", expand=True, padx=PAD, pady=(8, PAD))

        tk.Label(log_outer, text="Logged Entries", font=("Segoe UI", 10),
                 fg=SUBTLE, bg=BG).pack(anchor="w")

        cols = ("Description", "Start Time", "Duration")
        col_widths = (200, 150, 90)

        # Header row
        hdr_frame = tk.Frame(log_outer, bg=SURFACE)
        hdr_frame.pack(fill="x")
        for col, w in zip(cols, col_widths):
            tk.Label(hdr_frame, text=col, font=("Segoe UI", 9, "bold"),
                     fg=SUBTLE, bg=SURFACE, width=w // 8, anchor="w",
                     padx=6, pady=4).pack(side="left")

        # Scrollable rows
        list_container = tk.Frame(log_outer, bg=BG)
        list_container.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_container)
        scrollbar.pack(side="right", fill="y")

        self._log_canvas = tk.Canvas(
            list_container, bg=BG, highlightthickness=0,
            yscrollcommand=scrollbar.set, height=200,
        )
        self._log_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._log_canvas.yview)

        self._log_frame = tk.Frame(self._log_canvas, bg=BG)
        self._log_canvas_window = self._log_canvas.create_window(
            (0, 0), window=self._log_frame, anchor="nw"
        )
        self._log_frame.bind("<Configure>", self._on_log_frame_configure)
        self._log_canvas.bind("<Configure>", self._on_canvas_configure)

        self._col_widths = col_widths
        self._log_colors = (BG, SURFACE)
        self._refresh_log()

    def _on_log_frame_configure(self, _event=None):
        self._log_canvas.configure(scrollregion=self._log_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._log_canvas.itemconfig(self._log_canvas_window, width=event.width)

    # ------------------------------------------------------------------
    # Timer logic
    # ------------------------------------------------------------------

    def _toggle(self):
        with self._lock:
            if not self._running:
                self._start_time = time.monotonic()
                self._start_dt = datetime.now()
                self._running = True
                self._update_ui_running(True)
            else:
                end_dt = datetime.now()
                elapsed = time.monotonic() - self._start_time
                duration_str = format_elapsed(elapsed)
                description = self._desc_var.get().strip() or "(no description)"
                self._running = False
                self._start_time = None
                self._update_ui_running(False)
                self._timer_label.config(text="00:00")
                append_csv(description, self._start_dt, end_dt, duration_str)
                self._desc_var.set("")
                self._refresh_log()

    def _update_ui_running(self, is_running: bool):
        c = self._colors
        if is_running:
            self._status_label.config(text="Running…", fg=c["green"])
            self._toggle_btn.config(text="■  Stop", bg=c["red"])
        else:
            self._status_label.config(text="Stopped", fg=c["subtle"])
            self._toggle_btn.config(text="▶  Start", bg=c["green"])

    def _tick(self):
        with self._lock:
            if self._running and self._start_time is not None:
                elapsed = time.monotonic() - self._start_time
                self._timer_label.config(text=format_elapsed(elapsed))
        self.root.after(500, self._tick)

    # ------------------------------------------------------------------
    # Log display
    # ------------------------------------------------------------------

    def _refresh_log(self):
        for widget in self._log_frame.winfo_children():
            widget.destroy()

        rows = load_csv_rows()
        rows.reverse()  # newest first

        for i, row in enumerate(rows):
            bg = self._log_colors[i % 2]
            values = (
                row.get("Description", ""),
                row.get("Start Time", ""),
                row.get("Duration", ""),
            )
            row_frame = tk.Frame(self._log_frame, bg=bg)
            row_frame.pack(fill="x")
            for val, w in zip(values, self._col_widths):
                tk.Label(
                    row_frame, text=val,
                    font=("Segoe UI", 9), fg=self._colors["text"],
                    bg=bg, anchor="w", padx=6, pady=3,
                    width=w // 8,
                ).pack(side="left")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = TimerApp(root)
    root.mainloop()
