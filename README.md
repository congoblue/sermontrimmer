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

## Troubleshooting

- **Transcribe crashes with no error message / the app just vanishes.**
  Transcription runs faster-whisper's Whisper model in a separate
  worker process (see `transcriber.py`), specifically so that if that
  native code crashes, the app can catch it and show a proper error
  dialog instead of silently dying. If you see an error dialog naming
  a Windows crash code (e.g. "access violation" / "illegal
  instruction"), that's this safety net working as intended — the
  message it shows explains what the code means and what to try.

- **"An access violation" during Transcribe, even on a CPU that
  supports AVX2.** This has been traced (on a Windows 10th-gen Intel
  machine) to a missing/outdated **Microsoft Visual C++
  Redistributable** — ctranslate2 (faster-whisper's backend) depends
  on it, and without it the native model-loading code can crash the
  moment it initializes, even though the DLL itself loads fine.
  Install/repair the latest x64 redistributable directly from
  Microsoft: https://aka.ms/vs/17/release/vc_redist.x64.exe — this
  fixed the issue in practice and is the first thing to try for this
  particular crash.

- **"An illegal instruction" during Transcribe.** This usually means
  the CPU itself doesn't support an instruction set (e.g. AVX2) that
  ctranslate2's optimized code needs. Try a smaller Whisper model, or
  transcribe on a different machine.

- **Still crashing after the above?** Try clearing the cached model
  weights and letting them re-download (rules out a corrupted/partial
  download):
  ```
  rmdir /s /q "%USERPROFILE%\.cache\huggingface\hub"
  ```
  or reinstall the transcription backend:
  ```
  pip install --force-reinstall faster-whisper ctranslate2
  ```
