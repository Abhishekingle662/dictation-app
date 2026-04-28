import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

model = WhisperModel(
    "large-v3",
    device="cuda",
    compute_type="float16"
)

print("Starting continuous live transcription (Press Ctrl+C to stop)...")
duration = 5  # Record in 5-second chunks
sample_rate = 16000

try:
    while True:
        print("\nListening (5 seconds)...")
        # Record audio from microphone
        audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
        sd.wait()
        
        # Flatten the audio to a 1D array as expected by faster-whisper
        audio_data = audio.flatten()

        segments, info = model.transcribe(
            audio_data,
            language="en",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )

        text = " ".join(s.text.strip() for s in segments)
        if text:
            print(f"> {text}")
except KeyboardInterrupt:
    print("\nTranscription stopped.")
