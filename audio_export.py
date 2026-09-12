"""
audio_export.py

Trims an audio (or video) file to an in/out time range and converts
its audio track to 22050 Hz mono MP3 using ffmpeg (must be installed
and on PATH). Any video track on the input is ignored.
"""

import shutil
import subprocess


def check_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def export_trimmed_mp3(
    input_path: str,
    output_path: str,
    start_seconds: float,
    end_seconds: float,
    sample_rate: int = 22050,
    channels: int = 1,
    bitrate: str = "32k",
) -> None:
    """
    Trim [start_seconds, end_seconds] from input_path and write an MP3
    at output_path, resampled to `sample_rate` Hz with `channels` channel(s).

    Raises RuntimeError if ffmpeg is missing or the command fails, or
    ValueError if the time range is invalid.
    """
    if not check_ffmpeg_available():
        raise RuntimeError(
            "ffmpeg was not found on your PATH. Install it from "
            "https://ffmpeg.org/download.html and make sure 'ffmpeg' "
            "runs from a terminal before exporting."
        )

    if end_seconds <= start_seconds:
        raise ValueError("Out point must be after the In point.")

    duration = end_seconds - start_seconds

    cmd = [
        "ffmpeg",
        "-y",                            # overwrite output without prompting
        "-ss", f"{start_seconds:.3f}",   # seek to in-point (fast + accurate for audio)
        "-i", input_path,
        "-t", f"{duration:.3f}",         # clip length
        "-vn",                           # ignore any video track (e.g. a video file input)
        "-ar", str(sample_rate),         # resample rate
        "-ac", str(channels),            # channel count (1 = mono)
        "-codec:a", "libmp3lame",
        "-b:a", bitrate,
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
