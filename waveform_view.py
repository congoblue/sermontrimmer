"""
waveform_view.py

A zoomable, pannable waveform Canvas widget with draggable In/Out
markers, a clickable playback cursor, and drag-to-select a region.
Pure Tkinter (no matplotlib/numpy) so it stays lightweight.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from waveform import Waveform

MARKER_GRAB_PX = 6  # how close (in pixels) a click must be to grab a marker
DRAG_THRESHOLD_PX = 4  # movement below this is treated as a click, not a region drag


class WaveformView(ttk.Frame):
    def __init__(
        self,
        parent,
        on_in_change: Callable[[float], None],
        on_out_change: Callable[[float], None],
        on_cursor_change: Optional[Callable[[float], None]] = None,
        on_region_change: Optional[Callable[[Optional[float], Optional[float]], None]] = None,
        height: int = 150,
    ):
        super().__init__(parent)
        self.on_in_change = on_in_change
        self.on_out_change = on_out_change
        self.on_cursor_change = on_cursor_change
        self.on_region_change = on_region_change

        self.waveform: Optional[Waveform] = None
        self.duration = 0.0
        self.view_start = 0.0
        self.view_duration = 0.0
        self.in_point: Optional[float] = None
        self.out_point: Optional[float] = None
        self.cursor: Optional[float] = None
        self.region_start: Optional[float] = None
        self.region_end: Optional[float] = None
        # "in", "out", "region" (new selection drag), "region_start"/"region_end"
        # (resizing an existing region's edge) while a drag is active.
        self._dragging: Optional[str] = None
        self._drag_start_x: Optional[int] = None
        self._drag_start_t: Optional[float] = None
        self._drag_fixed_edge: Optional[float] = None  # the region edge NOT being dragged

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
        self.canvas.bind("<Motion>", self._on_hover)

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

    def set_cursor(self, t: Optional[float]):
        self.cursor = t
        self._redraw()

    def clear_region(self):
        self.region_start = None
        self.region_end = None
        self._redraw()

    def clear(self):
        self.waveform = None
        self.duration = 0.0
        self.view_start = 0.0
        self.view_duration = 0.0
        self.in_point = None
        self.out_point = None
        self.cursor = None
        self.region_start = None
        self.region_end = None
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

    def _near_region_edge(self, x: float) -> Optional[str]:
        if self.region_start is None or self.region_end is None:
            return None
        if abs(self._time_to_x(self.region_start) - x) <= MARKER_GRAB_PX:
            return "start"
        if abs(self._time_to_x(self.region_end) - x) <= MARKER_GRAB_PX:
            return "end"
        return None

    def _on_press(self, event):
        edge = self._near_region_edge(event.x)
        if self.in_point is not None and abs(self._time_to_x(self.in_point) - event.x) <= MARKER_GRAB_PX:
            self._dragging = "in"
        elif self.out_point is not None and abs(self._time_to_x(self.out_point) - event.x) <= MARKER_GRAB_PX:
            self._dragging = "out"
        elif edge == "start":
            self._dragging = "region_start"
            self._drag_fixed_edge = self.region_end
        elif edge == "end":
            self._dragging = "region_end"
            self._drag_fixed_edge = self.region_start
        elif self.waveform:
            self._dragging = "region"
            self._drag_start_x = event.x
            self._drag_start_t = max(0.0, min(self.duration, self._x_to_time(event.x)))
            self.region_start = self._drag_start_t
            self.region_end = self._drag_start_t
            self._redraw()
        else:
            self._dragging = None

    def _on_drag(self, event):
        if not self._dragging or not self.waveform:
            return
        if self._dragging == "region":
            t = max(0.0, min(self.duration, self._x_to_time(event.x)))
            self.region_start = min(self._drag_start_t, t)
            self.region_end = max(self._drag_start_t, t)
            self._redraw()
            return
        if self._dragging in ("region_start", "region_end"):
            t = max(0.0, min(self.duration, self._x_to_time(event.x)))
            self.region_start, self.region_end = sorted((t, self._drag_fixed_edge))
            self._redraw()
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
        elif self._dragging in ("region_start", "region_end"):
            if self.on_region_change:
                self.on_region_change(self.region_start, self.region_end)
        elif self._dragging == "region":
            moved = self._drag_start_x is not None and abs(event.x - self._drag_start_x) > DRAG_THRESHOLD_PX
            if moved:
                if self.on_region_change:
                    self.on_region_change(self.region_start, self.region_end)
            else:
                # Not a real drag: treat as a plain click that moves the cursor
                # and clears any previously selected region.
                self.region_start = None
                self.region_end = None
                if self.on_region_change:
                    self.on_region_change(None, None)
                self._move_cursor(self._drag_start_x)
        self._dragging = None
        self._drag_start_x = None
        self._drag_start_t = None
        self._drag_fixed_edge = None

    def _near_marker(self, x: float) -> bool:
        if self.in_point is not None and abs(self._time_to_x(self.in_point) - x) <= MARKER_GRAB_PX:
            return True
        if self.out_point is not None and abs(self._time_to_x(self.out_point) - x) <= MARKER_GRAB_PX:
            return True
        return False

    def _on_hover(self, event):
        if self._dragging:
            return
        if self._near_marker(event.x) or self._near_region_edge(event.x) is not None:
            self.canvas.config(cursor="sb_h_double_arrow")
        else:
            self.canvas.config(cursor="")

    def _move_cursor(self, x: float):
        t = max(0.0, min(self.duration, self._x_to_time(x)))
        self.cursor = t
        self._redraw()
        if self.on_cursor_change:
            self.on_cursor_change(t)

    def _draw_range_tint(self, start: float, end: float, h: float, fill: str, stipple: str):
        if end <= start or end < self.view_start or start > self.view_start + self.view_duration:
            return
        rs = max(start, self.view_start)
        re = min(end, self.view_start + self.view_duration)
        self.canvas.create_rectangle(
            self._time_to_x(rs), 0, self._time_to_x(re), h, fill=fill, outline="", stipple=stipple
        )

    def _redraw(self):
        self.canvas.delete("all")
        if not self.waveform:
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        mid = h / 2

        # Transcribe-region selection (blue) and the In/Out trim range
        # (orange) are tinted with different stipple patterns so the two
        # can overlap and both stay visible rather than one hiding the other.
        if self.region_start is not None and self.region_end is not None:
            self._draw_range_tint(self.region_start, self.region_end, h, "#2f6fa6", "gray25")
        if self.in_point is not None and self.out_point is not None:
            self._draw_range_tint(self.in_point, self.out_point, h, "#c76b1e", "gray50")

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
        if self.cursor is not None and self.view_start <= self.cursor <= self.view_start + self.view_duration:
            x = self._time_to_x(self.cursor)
            self.canvas.create_line(x, 0, x, h, fill="#ffffff", width=1)

        self._update_scrollbar()

    def _update_scrollbar(self):
        if not self.waveform or self.duration <= 0:
            self.scrollbar.set(0, 1)
            return
        lo = self.view_start / self.duration
        hi = (self.view_start + self.view_duration) / self.duration
        self.scrollbar.set(lo, hi)
