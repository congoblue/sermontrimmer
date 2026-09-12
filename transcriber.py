"""
transcriber.py

Wraps faster-whisper to produce a list of timestamped segments from
an audio file. Runs fully locally/offline once the model weights have
been downloaded once (first run per model size needs internet).
"""

from dataclasses import dataclass
from typing import List, Callable, Optional, Sequence

from faster_whisper import WhisperModel


@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str


def transcribe(
    audio_path: str,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    progress_callback: Optional[Callable[[str], None]] = None,
    clip_timestamps: Optional[Sequence[float]] = None,
    language: Optional[str] = "en",
) -> List[Segment]:
    """
    Transcribe an audio file and return a list of Segment objects with
    start/end times in seconds.

    model_size: one of "tiny", "base", "small", "medium", "large-v3".
                Bigger = more accurate but slower and needs more RAM.
    clip_timestamps: optional [start, end] (seconds) to only transcribe
                     that slice of the audio; returned Segment times
                     stay relative to the full original file. Defaults
                     to the whole file.
    language: force this language code (default "en") instead of
              letting Whisper auto-detect it from the audio, which can
              misfire on accented speech, singing, etc. Pass None to
              restore auto-detection.
    """
    if progress_callback:
        progress_callback(f"Loading Whisper model '{model_size}'...")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    if progress_callback:
        progress_callback("Transcribing audio (this can take a while)...")

    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        clip_timestamps=list(clip_timestamps) if clip_timestamps else "0",
        language=language,
    )

    segments: List[Segment] = []
    for seg in segments_iter:
        segments.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip()))
        if progress_callback:
            progress_callback(f"...transcribed up to {format_timestamp(seg.end)}")

    if progress_callback:
        progress_callback(f"Done. {len(segments)} segments, language={info.language}")

    return segments


def format_timestamp(seconds: float) -> str:
    """Convert seconds -> HH:MM:SS.mmm string for display."""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"
