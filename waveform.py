"""
waveform.py

Decodes an audio file to a low-resolution peak envelope (min/max per
time bucket) using ffmpeg, so the waveform view can draw and zoom
quickly without needing numpy or reprocessing the full-resolution
audio on every redraw.
"""

import shutil
import struct
import subprocess
from dataclasses import dataclass
from typing import List, Tuple

DECODE_SAMPLE_RATE = 4000   # low rate is plenty for a visual peak envelope
PEAKS_PER_SECOND = 100      # resolution of the stored peak envelope


@dataclass
class Waveform:
    duration: float                    # seconds
    peaks: List[Tuple[float, float]]   # (min, max) pairs, one per 1/PEAKS_PER_SECOND

    def peaks_per_second(self) -> int:
        return PEAKS_PER_SECOND


def load_waveform(audio_path: str) -> Waveform:
    """
    Decode audio_path to mono 16-bit PCM via ffmpeg, then bucket the
    samples into min/max peak pairs for drawing. Raises RuntimeError if
    ffmpeg is missing or decoding fails.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to build the waveform preview.")

    cmd = [
        "ffmpeg", "-v", "error", "-i", audio_path,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(DECODE_SAMPLE_RATE), "-ac", "1",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to decode audio:\n{result.stderr.decode(errors='ignore')}"
        )

    raw = result.stdout
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
