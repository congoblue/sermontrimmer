"""
waveform.py

Decodes an audio file to a low-resolution peak envelope (min/max per
time bucket) using ffmpeg, so the waveform view can draw and zoom
quickly without needing numpy or reprocessing the full-resolution
audio on every redraw.
"""

import re
import shutil
import struct
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

DECODE_SAMPLE_RATE = 4000   # low rate is plenty for a visual peak envelope
PEAKS_PER_SECOND = 100      # resolution of the stored peak envelope


@dataclass
class Waveform:
    duration: float                    # seconds
    peaks: List[Tuple[float, float]]   # (min, max) pairs, one per 1/PEAKS_PER_SECOND

    def peaks_per_second(self) -> int:
        return PEAKS_PER_SECOND


def _probe_duration(audio_path: str) -> float:
    """
    Return the audio's duration in seconds, or 0.0 if it can't be
    determined. Prefers ffprobe; falls back to parsing the "Duration:"
    line ffmpeg itself prints (ffprobe isn't always bundled alongside
    ffmpeg, e.g. some Windows installs only ship ffmpeg.exe).
    """
    if shutil.which("ffprobe"):
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return float(result.stdout.strip())
        except (OSError, ValueError):
            pass

    try:
        result = subprocess.run(["ffmpeg", "-i", audio_path], capture_output=True, text=True)
    except OSError:
        return 0.0
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return 0.0
    hrs, mins, secs = match.groups()
    return int(hrs) * 3600 + int(mins) * 60 + float(secs)


def _parse_out_time(line: str) -> Optional[float]:
    """Parse an ffmpeg `-progress` "out_time=HH:MM:SS.ffffff" line into seconds."""
    if not line.startswith("out_time="):
        return None
    value = line.split("=", 1)[1].strip()
    try:
        hrs, mins, secs = value.split(":")
        return int(hrs) * 3600 + int(mins) * 60 + float(secs)
    except ValueError:
        return None


def load_waveform(
    audio_path: str, progress_callback: Optional[Callable[[float], None]] = None
) -> Waveform:
    """
    Decode audio_path to mono 16-bit PCM via ffmpeg, then bucket the
    samples into min/max peak pairs for drawing. Raises RuntimeError if
    ffmpeg is missing or decoding fails.

    progress_callback, if given, is called with a 0-100 percent-complete
    value as ffmpeg decodes.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to build the waveform preview.")

    total_duration = _probe_duration(audio_path) if progress_callback else 0.0

    cmd = [
        "ffmpeg", "-v", "error", "-i", audio_path,
        "-progress", "pipe:2",
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(DECODE_SAMPLE_RATE), "-ac", "1",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    stdout_chunks: List[bytes] = []

    def _drain_stdout():
        while True:
            chunk = proc.stdout.read(1 << 20)
            if not chunk:
                break
            stdout_chunks.append(chunk)

    reader = threading.Thread(target=_drain_stdout, daemon=True)
    reader.start()

    stderr_lines: List[str] = []
    for raw_line in proc.stderr:
        line = raw_line.decode(errors="ignore").strip()
        stderr_lines.append(line)
        if progress_callback and total_duration > 0:
            out_time = _parse_out_time(line)
            if out_time is not None:
                pct = max(0.0, min(100.0, out_time / total_duration * 100.0))
                progress_callback(pct)

    reader.join()
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed to decode audio:\n" + "\n".join(stderr_lines))

    if progress_callback:
        progress_callback(100.0)

    raw = b"".join(stdout_chunks)
    num_samples = len(raw) // 2
    samples = struct.unpack(f"<{num_samples}h", raw[: num_samples * 2])

    samples_per_bucket = max(1, DECODE_SAMPLE_RATE // PEAKS_PER_SECOND)
    peaks: List[Tuple[float, float]] = []
    for i in range(0, num_samples, samples_per_bucket):
        chunk = samples[i : i + samples_per_bucket]
        if not chunk:
            continue
        peaks.append((min(chunk) / 32768.0, max(chunk) / 32768.0))

    duration = num_samples / DECODE_SAMPLE_RATE
    return Waveform(duration=duration, peaks=peaks)
