"""
audio_player.py

Minimal WAV-based playback for previewing the loaded recording.

The input file's audio track is decoded once (via ffmpeg) to a local
temp WAV at a modest listening quality. "Playing from an offset" is
done by slicing that WAV (pure file I/O - fast, no re-encoding) and
handing the slice to the standard library's `winsound` module, which
is the only playback backend used here (Windows only - this app
already assumes a Windows desktop environment elsewhere).
"""

import os
import shutil
import subprocess
import tempfile
import wave
from typing import Callable, Optional

try:
    import winsound
    PLAYBACK_AVAILABLE = True
except ImportError:  # pragma: no cover - non-Windows platforms
    winsound = None
    PLAYBACK_AVAILABLE = False

PLAYBACK_SAMPLE_RATE = 22050
PLAYBACK_CHANNELS = 1


def decode_to_wav(audio_path: str) -> str:
    """
    Decode audio_path's audio track to a local temp WAV file suitable
    for playback, and return its path. Raises RuntimeError if ffmpeg is
    missing or decoding fails. Caller is responsible for deleting the
    returned file (Player.close() does this).
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for audio playback.")

    fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="sermontrimmer_play_")
    os.close(fd)

    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", audio_path,
        "-vn",  # ignore any video track (e.g. a video file input)
        "-ar", str(PLAYBACK_SAMPLE_RATE), "-ac", str(PLAYBACK_CHANNELS),
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        _silently_remove(out_path)
        raise RuntimeError(f"ffmpeg failed to decode audio for playback:\n{result.stderr}")
    return out_path


def _silently_remove(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


class Player:
    """
    Wraps winsound playback of a locally-decoded WAV file, supporting
    play-from-offset / stop against a single master WAV. There is no
    native "pause" in winsound; callers implement pause by calling
    stop_sound() and remembering where playback had gotten to, then
    resuming via play_from() at that same position.
    """

    def __init__(self, wav_path: str):
        self.wav_path = wav_path
        self._slice_path: Optional[str] = None

    def play_from(self, start_seconds: float, should_still_play: Optional[Callable[[], bool]] = None) -> None:
        """
        Start playing from start_seconds. If should_still_play is given,
        it's checked right before playback actually starts (after the
        slice has been prepared) and playback is skipped if it returns
        False - lets a caller cancel a play that's since been
        superseded by a newer pause/stop/play without racing on time.
        """
        if not PLAYBACK_AVAILABLE:
            raise RuntimeError("Audio playback is only supported on Windows.")

        self.stop_sound()
        self._cleanup_slice()
        self._slice_path = self._extract_slice(start_seconds)

        if should_still_play is not None and not should_still_play():
            return
        winsound.PlaySound(self._slice_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

    def stop_sound(self) -> None:
        if PLAYBACK_AVAILABLE:
            winsound.PlaySound(None, winsound.SND_PURGE)

    def close(self) -> None:
        self.stop_sound()
        self._cleanup_slice()
        _silently_remove(self.wav_path)

    def _cleanup_slice(self) -> None:
        _silently_remove(self._slice_path)
        self._slice_path = None

    def _extract_slice(self, start_seconds: float) -> str:
        with wave.open(self.wav_path, "rb") as src:
            n_channels = src.getnchannels()
            sampwidth = src.getsampwidth()
            framerate = src.getframerate()
            n_frames = src.getnframes()

            start_frame = max(0, min(n_frames, int(start_seconds * framerate)))
            src.setpos(start_frame)
            frames = src.readframes(n_frames - start_frame)

        fd, slice_path = tempfile.mkstemp(suffix=".wav", prefix="sermontrimmer_slice_")
        os.close(fd)
        with wave.open(slice_path, "wb") as dst:
            dst.setnchannels(n_channels)
            dst.setsampwidth(sampwidth)
            dst.setframerate(framerate)
            dst.writeframes(frames)
        return slice_path
