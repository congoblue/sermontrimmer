"""
app.py

Sermon Trimmer - simple desktop tool:
1. Open an audio recording of a church service.
2. Transcribe it locally with Whisper (via faster-whisper).
3. Pick In/Out points from the transcript, fine-tune on a zoomable
   waveform (drag the markers, or nudge them in small steps).
4. Export the selected range as a 22050 Hz mono, 32 kbps MP3, named
   ddmmyyRS.mp3 by default (nearest Sunday's date + "RS").

Run with: python app.py
"""

import os
import threading
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Optional

from transcriber import transcribe, format_timestamp, Segment
from audio_export import export_trimmed_mp3, check_ffmpeg_available
from waveform import load_waveform
from waveform_view import WaveformView

NUDGE_STEPS = [("-1s", -1.0), ("-0.1s", -0.1), ("+0.1s", 0.1), ("+1s", 1.0)]


def nearest_sunday(reference: Optional[datetime] = None) -> datetime:
    """Return the Sunday closest to `reference` (defaults to now)."""
    reference = reference or datetime.now()
    days_since_sunday = (reference.weekday() - 6) % 7  # Mon=0 .. Sun=6
    days_until_sunday = (6 - reference.weekday()) % 7
    if days_since_sunday <= days_until_sunday:
        return reference - timedelta(days=days_since_sunday)
    return reference + timedelta(days=days_until_sunday)


class SermonTrimmerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Sermon Trimmer")
        self.root.geometry("860x760")

        self.audio_path: Optional[str] = None
        self.duration: float = 0.0
        self.segments: List[Segment] = []
        self.in_point: Optional[float] = None
        self.out_point: Optional[float] = None

        self._build_ui()

    # ---------- UI construction ----------

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.open_btn = ttk.Button(top, text="Open Audio File...", command=self.open_file)
        self.open_btn.pack(side="left")

        self.file_label = ttk.Label(top, text="No file loaded")
        self.file_label.pack(side="left", padx=10)

        model_frame = ttk.Frame(self.root, padding=(8, 0))
        model_frame.pack(fill="x")
        ttk.Label(model_frame, text="Whisper model:").pack(side="left")
        self.model_var = tk.StringVar(value="base")
        model_combo = ttk.Combobox(
            model_frame, textvariable=self.model_var, state="readonly",
            values=["tiny", "base", "small", "medium", "large-v3"], width=12,
        )
        model_combo.pack(side="left", padx=6)

        self.transcribe_btn = ttk.Button(
            model_frame, text="Transcribe", command=self.start_transcription, state="disabled"
        )
        self.transcribe_btn.pack(side="left", padx=10)

        self.status_label = ttk.Label(self.root, text="", padding=(8, 4), foreground="#555")
        self.status_label.pack(fill="x")
        self.waveform_status_label = ttk.Label(self.root, text="", padding=(8, 0), foreground="#555")
        self.waveform_status_label.pack(fill="x")

        # Transcript table
        columns = ("start", "end", "text")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", selectmode="browse", height=10)
        self.tree.heading("start", text="Start")
        self.tree.heading("end", text="End")
        self.tree.heading("text", text="Text")
        self.tree.column("start", width=90, anchor="center")
        self.tree.column("end", width=90, anchor="center")
        self.tree.column("text", width=620, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        tree_scroll = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")

        # Waveform preview
        self.waveform_view = WaveformView(
            self.root, on_in_change=self._set_in, on_out_change=self._set_out
        )
        self.waveform_view.pack(fill="x", padx=8, pady=(4, 8))

        # In/Out controls (set from transcript selection)
        io_frame = ttk.Frame(self.root, padding=8)
        io_frame.pack(fill="x")

        ttk.Button(io_frame, text="Set In (segment start)", command=self.set_in_from_transcript).pack(side="left")
        ttk.Button(io_frame, text="Set Out (segment end)", command=self.set_out_from_transcript).pack(side="left", padx=6)

        self.io_label = ttk.Label(io_frame, text="In: --   Out: --")
        self.io_label.pack(side="left", padx=20)

        # Nudge controls (fine adjustment in small steps)
        nudge_frame = ttk.Frame(self.root, padding=(8, 0))
        nudge_frame.pack(fill="x")

        ttk.Label(nudge_frame, text="Nudge In:").pack(side="left")
        for label, delta in NUDGE_STEPS:
            ttk.Button(nudge_frame, text=label, width=5, command=lambda d=delta: self._nudge_in(d)).pack(
                side="left", padx=2
            )

        ttk.Label(nudge_frame, text="   Nudge Out:").pack(side="left", padx=(20, 0))
        for label, delta in NUDGE_STEPS:
            ttk.Button(nudge_frame, text=label, width=5, command=lambda d=delta: self._nudge_out(d)).pack(
                side="left", padx=2
            )

        export_frame = ttk.Frame(self.root, padding=8)
        export_frame.pack(fill="x")
        self.export_btn = ttk.Button(
            export_frame, text="Export MP3...", command=self.export_mp3, state="disabled"
        )
        self.export_btn.pack(side="left")
        ttk.Label(export_frame, text="  (22050 Hz mono, 32 kbps, saved as ddmmyyRS.mp3)").pack(side="left")

        if not check_ffmpeg_available():
            messagebox.showwarning(
                "ffmpeg not found",
                "ffmpeg was not found on your PATH. You can still transcribe, "
                "but the waveform preview and export will fail until ffmpeg is installed.",
            )

    # ---------- File loading ----------

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Select audio recording",
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg"), ("All files", "*.*")],
        )
        if not path:
            return
        self.audio_path = path
        self.duration = 0.0
        self.file_label.config(text=os.path.basename(path))
        self.transcribe_btn.config(state="normal")
        self.segments = []
        self.tree.delete(*self.tree.get_children())
        self.in_point = None
        self.out_point = None
        self.io_label.config(text="In: --   Out: --")
        self.export_btn.config(state="disabled")
        self.waveform_view.clear()
        self.status_label.config(text="")

        self.start_waveform_load()

    # ---------- Waveform ----------

    def start_waveform_load(self):
        self.waveform_status_label.config(text="Loading waveform...")
        threading.Thread(target=self._run_waveform_load, daemon=True).start()

    def _run_waveform_load(self):
        try:
            waveform = load_waveform(self.audio_path)
        except Exception as e:
            self.root.after(0, lambda: self.waveform_status_label.config(text=f"Waveform failed: {e}"))
            return
        self.root.after(0, lambda: self._on_waveform_loaded(waveform))

    def _on_waveform_loaded(self, waveform):
        self.duration = waveform.duration
        self.waveform_view.set_waveform(waveform)
        self.waveform_view.set_markers(self.in_point, self.out_point)
        self.waveform_status_label.config(text=f"Waveform ready ({format_timestamp(waveform.duration)} total).")

    # ---------- Transcription ----------

    def start_transcription(self):
        if not self.audio_path:
            return
        self.transcribe_btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        threading.Thread(target=self._run_transcription, daemon=True).start()

    def _run_transcription(self):
        def progress(msg: str):
            self.root.after(0, lambda: self.status_label.config(text=msg))

        try:
            segments = transcribe(
                self.audio_path, model_size=self.model_var.get(), progress_callback=progress
            )
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Transcription failed", str(e)))
            self.root.after(0, lambda: self.transcribe_btn.config(state="normal"))
            self.root.after(0, lambda: self.open_btn.config(state="normal"))
            return

        self.segments = segments
        self.root.after(0, self._populate_tree)

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, seg in enumerate(self.segments):
            self.tree.insert(
                "", "end", iid=str(i),
                values=(format_timestamp(seg.start), format_timestamp(seg.end), seg.text),
            )
        self.transcribe_btn.config(state="normal")
        self.open_btn.config(state="normal")
        self.status_label.config(
            text=f"Transcribed {len(self.segments)} segments. Select a row, then Set In / Set Out."
        )

    def _selected_segment(self) -> Optional[Segment]:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Click a row in the transcript first.")
            return None
        return self.segments[int(sel[0])]

    def set_in_from_transcript(self):
        seg = self._selected_segment()
        if seg is not None:
            self._set_in(seg.start)

    def set_out_from_transcript(self):
        seg = self._selected_segment()
        if seg is not None:
            self._set_out(seg.end)

    # ---------- In/Out point management (shared by transcript, waveform drag, nudge) ----------

    def _set_in(self, t: float):
        t = max(0.0, t)
        if self.duration:
            t = min(t, self.duration)
        self.in_point = t
        self._sync_markers()

    def _set_out(self, t: float):
        t = max(0.0, t)
        if self.duration:
            t = min(t, self.duration)
        self.out_point = t
        self._sync_markers()

    def _nudge_in(self, delta: float):
        if self.in_point is None:
            messagebox.showinfo("No In point yet", "Set an In point first (from the transcript or waveform).")
            return
        self._set_in(self.in_point + delta)

    def _nudge_out(self, delta: float):
        if self.out_point is None:
            messagebox.showinfo("No Out point yet", "Set an Out point first (from the transcript or waveform).")
            return
        self._set_out(self.out_point + delta)

    def _sync_markers(self):
        in_str = format_timestamp(self.in_point) if self.in_point is not None else "--"
        out_str = format_timestamp(self.out_point) if self.out_point is not None else "--"
        self.io_label.config(text=f"In: {in_str}   Out: {out_str}")
        valid = (
            self.in_point is not None
            and self.out_point is not None
            and self.out_point > self.in_point
        )
        self.export_btn.config(state="normal" if valid else "disabled")
        self.waveform_view.set_markers(self.in_point, self.out_point)

    # ---------- Export ----------

    def export_mp3(self):
        if self.in_point is None or self.out_point is None:
            return
        default_name = nearest_sunday().strftime("%d%m%y") + "RS.mp3"
        out_path = filedialog.asksaveasfilename(
            title="Save sermon MP3 as...",
            defaultextension=".mp3",
            initialfile=default_name,
            filetypes=[("MP3 audio", "*.mp3")],
        )
        if not out_path:
            return
        try:
            export_trimmed_mp3(
                self.audio_path, out_path, self.in_point, self.out_point,
                sample_rate=22050, channels=1, bitrate="32k",
            )
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return
        messagebox.showinfo("Done", f"Saved: {out_path}")


def main():
    root = tk.Tk()
    SermonTrimmerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
