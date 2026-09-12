import sys
print("1: starting", flush=True)

from faster_whisper import WhisperModel
print("2: imported faster_whisper", flush=True)

m = WhisperModel("tiny", device="cpu", compute_type="float32")
print("3: model loaded", flush=True)

segments, info = m.transcribe(r"C:\path\to\any\short\audio\file.wav", beam_size=5)
print("4: transcribe() returned (still lazy - nothing decoded yet)", flush=True)

for s in segments:
    print(s.start, s.end, s.text)
print("5: OK, language=", info.language)