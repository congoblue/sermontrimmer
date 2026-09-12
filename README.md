# Sermon Trimmer

A small desktop app: open a recording of a church service, get a
timestamped transcript, click to pick the sermon's in/out points, and
export it as a 22050 Hz mono MP3.

## Setup

1. **Install Python 3.9+** if you don't already have it (python.org).

2. **Install ffmpeg** and make sure it's on your PATH. On Windows,
   the easiest route is `winget install ffmpeg` (or download a build
   from ffmpeg.org and add its `bin` folder to PATH). Test with:
   ```
   ffmpeg -version
   ```
   in a terminal — if that works, you're set.

3. **Install the Python dependencies:**
   ```
   pip install -r requirements.txt
   ```
   (`tkinter` ships with standard Python installs on Windows/Mac; on
   some Linux distros you may need `sudo apt install python3-tk`.)

## Running

```
python app.py
```

## Using it

1. **Open Audio File** — pick the service recording (mp3, wav, m4a, etc).
2. Pick a **Whisper model** size and click **Transcribe**:
   - `tiny`/`base` — fastest, good enough to find in/out points.
   - `small`/`medium`/`large-v3` — slower, more accurate wording (not
     usually necessary just for finding cut points).
   - The **first** time you use a given model size, it downloads the
     weights (needs internet, one-off). After that it's fully offline.
3. As soon as a file is opened, a **waveform preview** loads in the
   background (independent of transcription, so it's usually ready
   first).
4. Once transcribed, scroll the transcript. Click the row where the
   sermon starts, then **Set In (segment start)**. Click the row where
   it ends, then **Set Out (segment end)**.
5. **Fine-tune** using either:
   - The waveform: click **Zoom to Selection** to frame your cut
     points, then drag the red (In) or yellow (Out) line directly on
     the waveform. `+`/`-` zoom and the scrollbar let you pan/zoom
     anywhere in the file.
   - The **Nudge In / Nudge Out** buttons (±0.1s / ±1s) for precise
     keyboard-free adjustments once a point is set.
6. Click **Export MP3...**. The save dialog defaults the filename to
   `ddmmyyRS.mp3` (today's date + "RS") — change it if you want a
   different name. Output is always 22050 Hz mono, 32 kbps MP3.

## Notes / possible tweaks

- Transcription runs on CPU by default (`device="cpu"` in
  `transcriber.py`). If you have an NVIDIA GPU with CUDA set up, you
  can pass `device="cuda"` for a large speed boost.
- The waveform is built from a low-resolution peak envelope decoded
  once via ffmpeg (`waveform.py`), so zooming/panning stays fast even
  on long recordings — it doesn't re-decode audio on every redraw.
- `audio_export.py` and `waveform.py` are standalone modules — reusable
  if you later want to batch-process multiple recordings.
- The `ddmmyyRS.mp3` naming and 32 kbps/22050 Hz/mono settings are set
  as defaults in `app.py` / `audio_export.py` if you ever want to
  change the convention.
