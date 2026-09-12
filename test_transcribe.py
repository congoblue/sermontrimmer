from faster_whisper import WhisperModel

AUDIO_PATH = r"C:\path\to\any\short\audio\file.wav"  # <-- change this to a real file on your machine

m = WhisperModel("tiny", device="cpu", compute_type="float32")
segments, info = m.transcribe(AUDIO_PATH, beam_size=5)
for s in segments:
    print(s.start, s.end, s.text)
print("OK, language=", info.language)