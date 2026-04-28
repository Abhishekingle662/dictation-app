import sys
import threading
import io
import time
import requests
import queue
import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wavfile
from pynput import keyboard
import pyperclip
import json
import os

def load_settings():
    try:
        settings_path = os.path.join(os.path.dirname(__file__), '..', 'settings.json')
        with open(settings_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading settings: {e}. Using defaults.")
        return {
            "model": "large-v3",
            "language": "en",
            "use_llm_rewrite": True,
            "llm_model": "llama3",
            "hotkey": "f8",
            "duration": 5
        }

settings = load_settings()

# Configuration
BACKEND_URL = "http://127.0.0.1:8000/transcribe/file"
HOTKEY = getattr(keyboard.Key, settings.get("hotkey", "f8"), keyboard.Key.f8)
SAMPLE_RATE = 16000

# App State
is_recording = False
audio_buffer = []
keyboard_controller = keyboard.Controller()

def send_audio_to_backend(audio_data):
    """Sends recorded audio to backend and pastes the result."""
    print("Transcribing...")
    
    # Reload settings in case they changed
    current_settings = load_settings()
    
    # Save array to in-memory wav file
    wav_io = io.BytesIO()
    wavfile.write(wav_io, SAMPLE_RATE, audio_data)
    wav_io.seek(0)
    
    try:
        response = requests.post(
            BACKEND_URL, 
            files={"file": ("audio.wav", wav_io, "audio/wav")},
            data={
                "language": current_settings.get("language", "en"),
                "use_llm_rewrite": "true" if current_settings.get("use_llm_rewrite") else "false",
                "llm_model": current_settings.get("llm_model", "llama3")
            }
        )
        response.raise_for_status()
        
        result = response.json()
        text = result.get("text", "")
        if text:
            print(f"Transcribed: {text}")
            paste_text(text)
        else:
            print("No text recognized.")
            
    except Exception as e:
        print(f"Transcription failed: {e}")

def paste_text(text):
    """Pastes text to active window via clipboard."""
    pyperclip.copy(text)
    time.sleep(0.1)  # small delay for clipboard to register
    
    # Simulate ctrl+v
    with keyboard_controller.pressed(keyboard.Key.ctrl):
        keyboard_controller.press('v')
        keyboard_controller.release('v')
        
    print("Text pasted.")

def audio_callback(indata, frames, time_info, status):
    """Callback for sounddevice InputStream"""
    global is_recording, audio_buffer
    if is_recording:
        audio_buffer.append(indata.copy())

def start_recording():
    global is_recording, audio_buffer
    is_recording = True
    audio_buffer = []
    print("Recording started. Release hotkey to stop.")

def stop_recording():
    global is_recording, audio_buffer
    is_recording = False
    
    if not audio_buffer:
        print("No audio recorded.")
        return
        
    print("Recording stopped.")
    # Process audio off the main thread so we don't block the listener
    audio_data = np.concatenate(audio_buffer, axis=0)
    threading.Thread(target=send_audio_to_backend, args=(audio_data,)).start()

def on_press(key):
    global is_recording
    if key == HOTKEY and not is_recording:
        start_recording()

def on_release(key):
    global is_recording
    if key == HOTKEY and is_recording:
        stop_recording()

def main():
    print(f"Dictation Agent started. Hold F8 to record.")
    
    # Start audio stream (it will stay open, but we only append to buffer when is_recording=True)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', callback=audio_callback):
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()

if __name__ == "__main__":
    main()
