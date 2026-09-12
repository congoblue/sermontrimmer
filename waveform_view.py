"""
waveform_view.py

A zoomable, pannable waveform Canvas widget with draggable In/Out
markers. Pure Tkinter (no matplotlib/numpy) so it stays lightweight.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from waveform import Waveform

MARKER_GRAB_PX = 6  # how close (in pixels) a click must be to grab a marker


class WaveformView(ttk.Frame):
    def __init__(
        self,
        parent,
        on_in_change: Callable[[float], None],
        on_out_change: Callable[[float], None],
        height: int = 150,
    ):
        super().__init__(parent)
        self.on_in_change = on_in_change
        self.on_out_change = on_out_change

        self.waveform: Optional[Waveform] = None
        self.duration = 0.0
        self.view_start = 0.0
        self.view_duration = 0.0
        self.in_point: Optional[float] = None
        self.out_point: Optional[float] = None
        self._dragging: Optional[str] = None  # "in" or "out" while a drag is active

        controls = ttk.Frame(self)
        controls.pack(fill="x")
        ttk.Label(controls, text="Waveform  Zoom:").pack(side="left")
        ttk.Button(controls, text="-", width=2, command=self.zoom_out).pack(side="left")
        ttk.Button(controls, text="+", width=2, command=self.zoom_in).pack(side="left", padx=(2, 10))
        ttk.Button(controls, text="Zoom to Fit", command=self.zoom_to_fit).pack(side="left")
        ttk.Button(controls, text="Zoom to Selection", command=self.zoom_to_selection).pack(side="left", padx=6)

        self.canvas = tk.Canvas(self, height=height, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="x", expand=True)

        self.scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self._on_scroll)
        self.scrollbar.pack(fill="x")

        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    # ---------- public API ----------

    def set_waveform(self, waveform: Waveform):
        self.waveform = waveform
        self.duration = waveform.duration
        self.view_start = 0.0
        self.view_duration = self.duration
        self._redraw()

    def set_markers(self, in_point: Optional[float], out_point: Optional[float]):
        self.in_point = in_point
        self.out_point = out_point
        self._redraw()

    def clear(self):
        self.waveform = None
        self.duration = 0.0
        self.view_start = 0.0
        self.view_duration = 0.0
        self.in_point = None
        self.out_point = None
        self.canvas.delete("all")
        self.scrollbar.set(0, 1)

    def zoom_in(self):
        self._zoom(0.5)

    def zoom_out(self):
        self._zoom(2.0)

    def zoom_to_fit(self):
        if not self.waveform:
            return
        self.view_start = 0.0
        self.view_duration = self.duration
        self._redraw()

    def zoom_to_selection(self):
        if not self.waveform or self.in_point is None or self.out_point is None:
            return
        span = max(self.out_point - self.in_point, 0.5)
        pad = span * 0.15
        self.view_start = max(0.0, self.in_point - pad)
        self.view_duration = min(self.duration - self.view_start, span + 2 * pad)
        self._redraw()

    # ---------- internal ----------

    def _zoom(self, factor: float):
        if not self.waveform:
            return
        center = self.view_start + self.view_duration / 2
        new_duration = min(self.duration, max(0.5, self.view_duration * factor))
        self.view_duration = new_duration
        self.view_start = max(0.0, min(self.duration - new_duration, center - new_duration / 2))
        self._redraw()

    def _on_scroll(self, *args):
        if not self.waveform:
            return
        action = args[0]
        if action == "moveto":
            frac = float(args[1])
            self.view_start = max(0.0, min(self.duration - self.view_duration, frac * self.duration))
        elif action == "scroll":
            amount, unit = float(args[1]), args[2]
            step = self.view_duration * (0.9 if unit == "pages" else 0.05)
            self.view_start = max(0.0, min(self.duration - self.view_duration, self.view_start + amount * step))
        self._redraw()

    def _time_to_x(self, t: float) -> float:
        w = self.canvas.winfo_width()
        return (t - self.view_start) / self.view_duration * w

    def _x_to_time(self, x: float) -> float:
        w = self.canvas.winfo_width()
        return self.view_start + (x / max(w, 1)) * self.view_duration

    def _on_press(self, event):
        if self.in_point is not None and abs(self._time_to_x(self.in_point) - event.x) <= MARKER_GRAB_PX:
            self._dragging = "in"
        elif self.out_point is not None and abs(self._time_to_x(self.out_point) - event.x) <= MARKER_GRAB_PX:
            self._dragging = "out"
        else:
            self._dragging = None

    def _on_drag(self, event):
        if not self._dragging or not self.waveform:
            return
        t = max(0.0, min(self.duration, self._x_to_time(event.x)))
        if self._dragging == "in":
            self.in_point = t
        else:
            self.out_point = t
        self._redraw()

    def _on_release(self, event):
        if self._dragging == "in" and self.in_point is not None:
            self.on_in_change(self.in_point)
        elif self._dragging == "out" and self.out_point is not None:
            self.on_out_change(self.out_point)
        self._dragging = None

    def _redraw(self):
        self.canvas.delete("all")
        if not self.waveform:
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        mid = h / 2

        peaks = self.waveform.peaks
        pps = self.waveform.peaks_per_second()

        start_idx = int(self.view_start * pps)
        end_idx = min(len(peaks), int((self.view_start + self.view_duration) * pps))

        visible = peaks[start_idx:end_idx]
        n = len(visible)
        if n == 0 or w <= 1:
            self._update_scrollbar()
            return

        for x in range(w):
            i0 = int(x / w * n)
            i1 = max(i0 + 1, int((x + 1) / w * n))
            chunk = visible[i0:i1] or [visible[min(i0, n - 1)]]
            lo = min(c[0] for c in chunk)
            hi = max(c[1] for c in chunk)
            y0 = mid - hi * mid
            y1 = mid - lo * mid
            self.canvas.create_line(x, y0, x, y1, fill="#4fc3f7")

        if self.in_point is not None and self.view_start <= self.in_point <= self.view_start + self.view_duration:
            x = self._time_to_x(self.in_point)
            self.canvas.create_line(x, 0, x, h, fill="#ff5252", width=2)
        if self.out_point is not None and self.view_start <= self.out_point <= self.view_start + self.view_duration:
            x = self._time_to_x(self.out_point)
            self.canvas.create_line(x, 0, x, h, fill="#ffca28", width=2)

        self._update_scrollbar()

    def _update_scrollbar(self):
        if not self.waveform or self.duration <= 0:
            self.scrollbar.set(0, 1)
            return
        lo = self.view_start / self.duration
        hi = (self.view_start + self.view_duration) / self.duration
        self.scrollbar.set(lo, hi)
