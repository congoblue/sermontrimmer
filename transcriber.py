"""
transcriber.py

Wraps faster-whisper to produce a list of timestamped segments from
an audio file. Runs fully locally/offline once the model weights have
been downloaded once (first run per model size needs internet).

The actual Whisper call runs in a child process (see _transcribe_worker)
rather than in-process. faster-whisper's ctranslate2 backend can abort
the whole process with an illegal-instruction crash on CPUs that lack
the instruction sets (e.g. AVX2) its optimized kernels assume - a fault
Python's own try/except cannot catch, since the process dies before any
exception is ever raised. Running it in a subprocess means that crash
only kills the worker; this module detects it and raises a normal,
catchable RuntimeError instead of silently taking the whole app down.
"""

import multiprocessing as mp
import queue
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from faster_whisper import WhisperModel


@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str


# Common Windows crash codes (NTSTATUS values) the worker process can exit
# with, and what they usually mean for a native library like ctranslate2.
_WINDOWS_CRASH_CODES = {
    0xC0000005: (
        "an access violation",
        "This is usually caused by a corrupted or incomplete Whisper model "
        "download, or a faster-whisper/ctranslate2 install that isn't "
        "compatible with this machine. Try deleting the cached model under "
        "%USERPROFILE%\\.cache\\huggingface\\hub and letting it re-download, "
        "or reinstall with: pip install --force-reinstall faster-whisper ctranslate2",
    ),
    0xC000001D: (
        "an illegal instruction",
        "This usually means this computer's CPU doesn't support an "
        "instruction set (e.g. AVX2) the Whisper engine's optimized code "
        "needs. Try a smaller Whisper model, or transcribe on a different machine.",
    ),
    0xC00000FD: (
        "a stack overflow",
        "Try a smaller Whisper model or a shorter audio clip/region.",
    ),
    0xC0000409: (
        "a stack buffer overrun",
        "Try reinstalling faster-whisper: pip install --force-reinstall faster-whisper ctranslate2",
    ),
}


def _describe_crash(exitcode: Optional[int]) -> str:
    if exitcode is None:
        return "it did not exit cleanly."
    if exitcode < 0:
        return f"it was terminated by signal {-exitcode}."
    match = _WINDOWS_CRASH_CODES.get(exitcode & 0xFFFFFFFF)
    if match:
        name, hint = match
        return f"it crashed with {name} (exit code {exitcode}). {hint}"
    return (
        f"it exited with code {exitcode}. Try a smaller Whisper model, or "
        "reinstall faster-whisper: pip install --force-reinstall faster-whisper ctranslate2"
    )


def _transcribe_worker(
    audio_path: str,
    model_size: str,
    device: str,
    compute_type: str,
    clip_timestamps: Optional[Sequence[float]],
    language: Optional[str],
    out_queue: "mp.Queue",
) -> None:
    """Runs in the child process. Only ever communicates back via out_queue."""
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments_iter, info = model.transcribe(
            audio_path,
            beam_size=5,
            clip_timestamps=list(clip_timestamps) if clip_timestamps else "0",
            language=language,
        )
        raw_segments = []
        for seg in segments_iter:
            raw_segments.append((seg.start, seg.end, seg.text.strip()))
            out_queue.put(("progress", f"...transcribed up to {format_timestamp(seg.end)}"))
        out_queue.put(("done", raw_segments, info.language))
    except Exception as e:
        out_queue.put(("error", str(e)))


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

    ctx = mp.get_context("spawn")
    out_queue: "mp.Queue" = ctx.Queue()
    proc = ctx.Process(
        target=_transcribe_worker,
        args=(audio_path, model_size, device, compute_type, clip_timestamps, language, out_queue),
        daemon=True,
    )
    proc.start()

    if progress_callback:
        progress_callback("Transcribing audio (this can take a while)...")

    raw_segments: List[tuple] = []
    result_language = None
    error_message: Optional[str] = None
    got_result = False

    while proc.is_alive() or not out_queue.empty():
        try:
            kind, *payload = out_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if kind == "progress":
            if progress_callback:
                progress_callback(payload[0])
        elif kind == "done":
            raw_segments, result_language = payload
            got_result = True
        elif kind == "error":
            error_message = payload[0]
            got_result = True

    proc.join()

    if error_message:
        raise RuntimeError(error_message)

    if not got_result:
        raise RuntimeError(
            "The transcription engine crashed unexpectedly: " + _describe_crash(proc.exitcode)
        )

    segments = [Segment(start=s, end=e, text=t) for s, e, t in raw_segments]

    if progress_callback:
        progress_callback(f"Done. {len(segments)} segments, language={result_language}")

    return segments


def format_timestamp(seconds: float) -> str:
    """Convert seconds -> HH:MM:SS.mmm string for display."""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"
