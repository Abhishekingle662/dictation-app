"""
Dictation desktop app — single entry point.
Starts the FastAPI backend in a thread, listens for the configured hotkey,
and shows a system tray icon (green = idle, red = recording).
"""
import io
import json
import os
import sys
import threading
import time
import winsound

# When launched without a console (pythonw.exe / VBS), redirect output to a log file.
if sys.stdout is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictation.log"), "a", buffering=1)
    sys.stdout = sys.stderr = _log

import tkinter as tk
from tkinter import ttk

import numpy as np
import pyperclip
import requests
import scipy.io.wavfile as wavfile
import sounddevice as sd
import uvicorn
from PIL import Image, ImageDraw
from pynput import keyboard as kb
import pystray

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(ROOT, "settings.json")
BACKEND_URL = "http://127.0.0.1:8000/transcribe/file"
SAMPLE_RATE = 16000

# --- Mutable state ---
is_recording = False
audio_buffer = []
tray_icon = None


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {
            "model": "large-v3",
            "language": "en",
            "use_llm_rewrite": False,
            "llm_model": "llama3",
            "hotkey": "f8",
            "duration": 5,
        }


# --- Backend ---

def start_backend():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "backend_main",
        os.path.join(ROOT, "backend", "app", "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backend_main"] = mod
    spec.loader.exec_module(mod)  # triggers model load
    uvicorn.run(mod.app, host="127.0.0.1", port=8000, log_level="warning")


def wait_for_backend(timeout=120):
    for _ in range(timeout):
        try:
            requests.get("http://127.0.0.1:8000/docs", timeout=1)
            return True
        except Exception:
            time.sleep(1)
    return False


# --- Tray icon ---

def make_icon(state="idle"):
    # state: "loading" (grey), "idle" (green), "recording" (red)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if state == "loading":
        bg = (130, 130, 130, 255)
    elif state == "recording":
        bg = (210, 50, 50, 255)
    else:
        bg = (50, 170, 50, 255)
    draw.ellipse([2, 2, 62, 62], fill=bg)
    # Mic body
    draw.rectangle([27, 14, 37, 38], fill="white")
    # Mic arc (stand)
    draw.arc([20, 28, 44, 50], start=0, end=180, fill="white", width=3)
    # Mic stem + base
    draw.line([32, 50, 32, 56], fill="white", width=3)
    draw.line([26, 56, 38, 56], fill="white", width=3)
    return img


def update_tray(recording: bool):
    if tray_icon:
        tray_icon.icon = make_icon("recording" if recording else "idle")


# --- Recording ---

def audio_callback(indata, frames, time_info, status):
    if is_recording:
        audio_buffer.append(indata.copy())


def start_recording():
    global is_recording, audio_buffer
    if is_recording:
        return
    is_recording = True
    audio_buffer = []
    winsound.Beep(880, 80)
    update_tray(True)
    print("Recording...")


def stop_recording():
    global is_recording
    if not is_recording:
        return
    is_recording = False
    winsound.Beep(500, 150)
    update_tray(False)

    if not audio_buffer:
        print("No audio captured.")
        return

    data = np.concatenate(audio_buffer, axis=0)
    threading.Thread(target=transcribe_and_paste, args=(data,), daemon=True).start()


def transcribe_and_paste(audio_data):
    settings = load_settings()
    wav_io = io.BytesIO()
    wavfile.write(wav_io, SAMPLE_RATE, audio_data)
    wav_io.seek(0)

    try:
        resp = requests.post(
            BACKEND_URL,
            files={"file": ("audio.wav", wav_io, "audio/wav")},
            data={
                "language": settings.get("language", "en"),
                "use_llm_rewrite": "true" if settings.get("use_llm_rewrite") else "false",
                "llm_model": settings.get("llm_model", "llama3"),
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json().get("text", "").strip()
        if text:
            print(f"Transcribed: {text}")
            pyperclip.copy(text)
            time.sleep(0.1)
            ctrl = kb.Controller()
            with ctrl.pressed(kb.Key.ctrl):
                ctrl.press("v")
                ctrl.release("v")
        else:
            print("Nothing recognised.")
    except Exception as e:
        print(f"Transcription error: {e}")


# --- Hotkey listener (always supports both F8 and Ctrl+Space) ---

def make_listener():
    """Returns (on_press, on_release) that handle F8 and Ctrl+Space simultaneously."""
    ctrl_down = [False]
    started_with = [None]  # 'f8' or 'ctrl_space'

    def on_press(key):
        if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
            ctrl_down[0] = True
            return

        if is_recording:
            return

        if key == kb.Key.f8:
            started_with[0] = "f8"
            start_recording()
        elif key == kb.Key.space and ctrl_down[0]:
            started_with[0] = "ctrl_space"
            start_recording()

    def on_release(key):
        if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
            ctrl_down[0] = False
            if is_recording and started_with[0] == "ctrl_space":
                stop_recording()
            return

        if not is_recording:
            return

        if key == kb.Key.f8 and started_with[0] == "f8":
            stop_recording()
        elif key == kb.Key.space and started_with[0] == "ctrl_space":
            stop_recording()

    return on_press, on_release


# --- Settings window ---

def open_settings_window():
    def _run():
        settings = load_settings()

        win = tk.Tk()
        win.title("Dictation Settings")
        win.configure(bg="#2b2b2b")
        win.resizable(False, False)

        W, H = 400, 420
        win.update_idletasks()
        x = (win.winfo_screenwidth() - W) // 2
        y = (win.winfo_screenheight() - H) // 2
        win.geometry(f"{W}x{H}+{x}+{y}")
        win.attributes("-topmost", True)
        win.after(200, lambda: win.attributes("-topmost", False))

        BG, FG, ENTRY_BG = "#2b2b2b", "#f0f0f0", "#3c3c3c"
        FONT = ("Segoe UI", 9)

        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=ENTRY_BG, background=ENTRY_BG,
                        foreground=FG, selectbackground=ENTRY_BG, font=FONT)

        def field(parent, label_text, widget_factory):
            tk.Label(parent, text=label_text, bg=BG, fg="#aaaaaa",
                     font=FONT, anchor="w").pack(fill="x", padx=20, pady=(10, 2))
            return widget_factory(parent)

        def make_entry(parent, value):
            var = tk.StringVar(value=str(value))
            tk.Entry(parent, textvariable=var, bg=ENTRY_BG, fg=FG,
                     insertbackground=FG, relief="flat", font=FONT,
                     bd=6).pack(fill="x", padx=20)
            return var

        def make_combo(parent, value, choices):
            var = tk.StringVar(value=str(value))
            ttk.Combobox(parent, textvariable=var, values=choices,
                         state="readonly", font=FONT).pack(fill="x", padx=20)
            return var

        # Header
        tk.Label(win, text="Dictation Settings", bg=BG, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(pady=(20, 4))
        ttk.Separator(win).pack(fill="x", padx=20, pady=4)

        model_var    = field(win, "Whisper Model",
                             lambda p: make_combo(p, settings.get("model", "large-v3"),
                                                  ["base", "small", "medium", "large-v3", "large-v3-turbo"]))
        lang_var     = field(win, "Language Code  (e.g. en, fr, de)",
                             lambda p: make_entry(p, settings.get("language", "en")))
        hotkey_var   = field(win, "Hotkey",
                             lambda p: make_combo(p, settings.get("hotkey", "f8"),
                                                  ["f8", "ctrl+space"]))
        duration_var = field(win, "Record Duration (seconds)",
                             lambda p: make_entry(p, settings.get("duration", 5)))

        ttk.Separator(win).pack(fill="x", padx=20, pady=(14, 0))

        llm_var = tk.BooleanVar(value=settings.get("use_llm_rewrite", False))
        tk.Checkbutton(win, text="Use LLM Rewrite (Ollama)", variable=llm_var,
                       bg=BG, fg=FG, selectcolor=ENTRY_BG, activebackground=BG,
                       activeforeground=FG, font=FONT).pack(anchor="w", padx=16, pady=(10, 0))

        llm_model_var = field(win, "LLM Model  (e.g. llama3, phi3)",
                              lambda p: make_entry(p, settings.get("llm_model", "llama3")))

        status = tk.Label(win, text="", bg=BG, font=FONT)
        status.pack(pady=(6, 0))

        def save():
            try:
                new_settings = {
                    "model":           model_var.get(),
                    "language":        lang_var.get().strip(),
                    "hotkey":          hotkey_var.get(),
                    "duration":        int(duration_var.get()),
                    "use_llm_rewrite": llm_var.get(),
                    "llm_model":       llm_model_var.get().strip(),
                }
                with open(SETTINGS_PATH, "w") as f:
                    json.dump(new_settings, f, indent=4)
                try:
                    requests.post("http://127.0.0.1:8000/reload", timeout=2)
                except Exception:
                    pass
                status.config(text="Saved!", fg="#4caf50")
                win.after(1500, win.destroy)
            except Exception as e:
                status.config(text=f"Error: {e}", fg="#f44336")

        tk.Button(win, text="Save Settings", command=save,
                  bg="#1e88e5", fg="white", activebackground="#1565c0",
                  activeforeground="white", relief="flat", font=("Segoe UI", 10, "bold"),
                  cursor="hand2", pady=8).pack(fill="x", padx=20, pady=(8, 16))

        win.mainloop()

    threading.Thread(target=_run, daemon=True).start()


# --- Tray menu actions ---

def open_settings(icon, item):
    open_settings_window()


def quit_app(icon, item):
    icon.stop()
    os._exit(0)


# --- Main ---

def main():
    global tray_icon

    menu = pystray.Menu(
        pystray.MenuItem("Open Settings", open_settings),
        pystray.MenuItem("Quit", quit_app),
    )
    tray_icon = pystray.Icon(
        "dictation", make_icon("loading"), "Dictation — Loading model...", menu
    )

    # Show the tray icon immediately in a background thread
    threading.Thread(target=tray_icon.run, daemon=True).start()

    print("Starting backend (loading Whisper model)...")
    threading.Thread(target=start_backend, daemon=True).start()

    if not wait_for_backend():
        tray_icon.notify("Failed to load model. Check dictation.log.", "Dictation Error")
        print("Backend failed to start in time. Exiting.")
        sys.exit(1)

    # Model ready — update icon and notify
    tray_icon.icon = make_icon("idle")
    tray_icon.title = "Dictation  [F8 or Ctrl+Space]"
    tray_icon.notify("Ready! Hold F8 or Ctrl+Space to dictate.", "Dictation")
    winsound.Beep(660, 100)
    print("Backend ready.")

    on_press, on_release = make_listener()

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=audio_callback
    )
    stream.start()

    listener = kb.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    print("Ready. Hold F8 or Ctrl+Space to dictate.")
    threading.Event().wait()  # block until os._exit() from quit_app


if __name__ == "__main__":
    main()
