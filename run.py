"""
Dictation desktop app — single entry point.
Starts the FastAPI backend in a thread, listens for the configured hotkey,
and shows a system tray icon (green = idle, red = recording).
"""
import io
import os
import re
import sys
import threading
import time
import winsound
import webbrowser
from typing import Optional

from app_paths import get_data_dir, get_log_path, get_models_dir, load_settings, save_settings

# When launched without a console (pythonw.exe / VBS), redirect output to a log file.
# IMPORTANT: when frozen (PyInstaller one-file), we must NOT write next to the exe extraction dir.
if sys.stdout is None:
    log_path = get_log_path()
    _log = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
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

BACKEND_URL = "http://127.0.0.1:8000/transcribe/file"
SAMPLE_RATE = 16000

# --- Mutable state ---
is_recording = False
audio_buffer = []
tray_icon = None


APP_VERSION = "0.1.0"
GITHUB_REPO = os.environ.get("DICTATION_GITHUB_REPO", "Abhishekingle662/dictation")
_update_release_url: Optional[str] = None


def _hotkey_label(hotkey: str) -> str:
    hotkey = str(hotkey or "").lower()
    if hotkey == "ctrl+space":
        return "Ctrl+Space"
    if hotkey == "both":
        return "F8 or Ctrl+Space"
    return "F8"


def _releases_page_url() -> str:
    return f"https://github.com/{GITHUB_REPO}/releases"


def open_releases(icon=None, item=None):
    url = _update_release_url or _releases_page_url()
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Failed to open browser: {e}")


def _version_tuple(version_str: str) -> tuple[int, int, int]:
    nums = re.findall(r"\d+", str(version_str or ""))
    parts = [int(n) for n in nums[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def _is_newer(remote_version: str, local_version: str) -> bool:
    try:
        return _version_tuple(remote_version) > _version_tuple(local_version)
    except Exception:
        return str(remote_version).strip() != str(local_version).strip()


def check_for_updates_async():
    def _worker():
        global _update_release_url

        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        try:
            resp = requests.get(
                api_url,
                timeout=5,
                headers={"User-Agent": f"Dictation/{APP_VERSION}"},
            )
            if resp.status_code != 200:
                return
            data = resp.json() or {}
            tag = data.get("tag_name") or data.get("name")
            html_url = data.get("html_url")
            if not tag:
                return

            if _is_newer(str(tag), APP_VERSION):
                _update_release_url = str(html_url) if html_url else _releases_page_url()
                if tray_icon:
                    tray_icon.notify(f"Update available: {tag}", "Dictation Update")
        except Exception as e:
            print(f"Update check failed: {e}")

    threading.Thread(target=_worker, daemon=True).start()


def detect_cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def recommended_model_for_cuda_devices(cuda_devices: int) -> str:
    # Keep this intentionally simple for the first-run wizard.
    return "large-v3" if cuda_devices > 0 else "small"


def is_model_downloaded(model_name: str) -> bool:
    try:
        model_dir = get_models_dir() / str(model_name)
        return (model_dir / "model.bin").exists()
    except Exception:
        return False


def download_model_to_app_dir(model_name: str) -> tuple[bool, str]:
    try:
        from faster_whisper.utils import download_model

        model_dir = get_models_dir() / str(model_name)
        model_dir.mkdir(parents=True, exist_ok=True)
        download_model(str(model_name), output_dir=str(model_dir))
        return True, ""
    except Exception as e:
        return False, str(e)


# --- Backend ---

def start_backend():
    from backend.app import main as backend_main

    # Importing the module triggers model load; keep it in this background thread.
    uvicorn.run(backend_main.app, host="127.0.0.1", port=8000, log_level="warning")


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


# --- Hotkey listener ---

def make_listener():
    """Returns (on_press, on_release) that handle the configured hotkey.

    Supported values for settings["hotkey"]:
      - "f8"
      - "ctrl+space"
      - "both" (fallback / dev)
    """

    ctrl_down = [False]
    started_with = [None]  # 'f8' | 'ctrl_space'

    def _current_hotkey() -> str:
        try:
            return str(load_settings().get("hotkey", "f8")).lower()
        except Exception:
            return "f8"

    def on_press(key):
        if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
            ctrl_down[0] = True
            return

        if is_recording:
            return

        hotkey = _current_hotkey()

        if (hotkey in ("f8", "both")) and key == kb.Key.f8:
            started_with[0] = "f8"
            start_recording()
        elif (hotkey in ("ctrl+space", "both")) and key == kb.Key.space and ctrl_down[0]:
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
        wizard_mode = not bool(settings.get("wizard_completed", False))

        win = tk.Tk()
        win.title("Dictation Setup" if wizard_mode else "Dictation Settings")
        win.configure(bg="#2b2b2b")
        win.resizable(False, False)

        W, H = (420, 460) if wizard_mode else (400, 420)
        win.update_idletasks()
        x = (win.winfo_screenwidth() - W) // 2
        y = (win.winfo_screenheight() - H) // 2
        win.geometry(f"{W}x{H}+{x}+{y}")
        win.attributes("-topmost", True)
        win.after(200, lambda: win.attributes("-topmost", False))

        BG, FG, ENTRY_BG, MUTED = "#2b2b2b", "#f0f0f0", "#3c3c3c", "#aaaaaa"
        FONT = ("Segoe UI", 9)

        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=ENTRY_BG, background=ENTRY_BG,
                        foreground=FG, selectbackground=ENTRY_BG, font=FONT)

        def run_first_run_wizard():
            cuda_devices = {"count": 0}
            recommended_model = {"name": recommended_model_for_cuda_devices(0)}
            chosen_model = {"name": settings.get("model", "large-v3-turbo")}

            gpu_status_var = tk.StringVar(value="Detecting GPU…")
            recommended_var = tk.StringVar(value="")
            use_recommended_var = tk.BooleanVar(value=False)
            use_recommended_text = tk.StringVar(value="")
            hotkey_var = tk.StringVar(value=settings.get("hotkey", "f8"))
            status_var = tk.StringVar(value="")

            step = {"index": 0}

            def refresh_recommendation_text():
                rec = recommended_model["name"]
                recommended_var.set(f"Recommended model: {rec}")
                use_recommended_text.set(f"Download and use the recommended model ({rec})")

            def do_detect_gpu():
                try:
                    count = detect_cuda_device_count()
                    cuda_devices["count"] = count
                    recommended_model["name"] = recommended_model_for_cuda_devices(count)
                    if count > 0:
                        gpu_status_var.set(f"CUDA GPU detected ({count} device(s)).")
                    else:
                        gpu_status_var.set("No CUDA GPU detected.")
                    refresh_recommendation_text()
                except Exception as e:
                    gpu_status_var.set(f"GPU detection failed: {e}")
                    refresh_recommendation_text()

            def clear_body(body: tk.Frame):
                for child in body.winfo_children():
                    child.destroy()

            header = tk.Label(win, text="First-run Setup", bg=BG, fg=FG,
                              font=("Segoe UI", 13, "bold"))
            header.pack(pady=(20, 4))
            ttk.Separator(win).pack(fill="x", padx=20, pady=4)

            body = tk.Frame(win, bg=BG)
            body.pack(fill="both", expand=True)

            status_label = tk.Label(
                win,
                textvariable=status_var,
                bg=BG,
                fg=MUTED,
                font=FONT,
                wraplength=W - 40,
                justify="left",
            )
            status_label.pack(fill="x", padx=20, pady=(0, 8))

            nav = tk.Frame(win, bg=BG)
            nav.pack(fill="x", padx=20, pady=(0, 16))

            back_btn = tk.Button(
                nav,
                text="Back",
                bg=ENTRY_BG,
                fg=FG,
                activebackground=ENTRY_BG,
                activeforeground=FG,
                relief="flat",
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                pady=6,
                state="disabled",
            )
            back_btn.pack(side="left")

            next_btn = tk.Button(
                nav,
                text="Next",
                bg="#1e88e5",
                fg="white",
                activebackground="#1565c0",
                activeforeground="white",
                relief="flat",
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                pady=6,
            )
            next_btn.pack(side="right")

            def render_step():
                clear_body(body)

                idx = step["index"]
                back_btn.config(state="normal" if idx > 0 else "disabled")

                if idx == 0:
                    tk.Label(body, text="1/3  Detect GPU", bg=BG, fg=FG,
                             font=("Segoe UI", 11, "bold"), anchor="w").pack(
                        fill="x", padx=20, pady=(14, 6)
                    )
                    tk.Label(body, text="This helps pick a good model.", bg=BG, fg=MUTED,
                             font=FONT, anchor="w").pack(fill="x", padx=20, pady=(0, 10))

                    tk.Label(body, textvariable=gpu_status_var, bg=BG, fg=FG,
                             font=FONT, anchor="w").pack(fill="x", padx=20, pady=(0, 8))
                    tk.Label(body, textvariable=recommended_var, bg=BG, fg=FG,
                             font=FONT, anchor="w").pack(fill="x", padx=20, pady=(0, 10))

                    tk.Button(
                        body,
                        text="Detect GPU",
                        command=do_detect_gpu,
                        bg=ENTRY_BG,
                        fg=FG,
                        activebackground=ENTRY_BG,
                        activeforeground=FG,
                        relief="flat",
                        font=("Segoe UI", 9, "bold"),
                        cursor="hand2",
                        pady=6,
                    ).pack(padx=20, anchor="w")

                    tk.Label(
                        body,
                        text=f"Data folder: {get_data_dir()}",
                        bg=BG,
                        fg=MUTED,
                        font=("Segoe UI", 8),
                        anchor="w",
                        wraplength=W - 40,
                        justify="left",
                    ).pack(fill="x", padx=20, pady=(14, 0))

                    next_btn.config(text="Next")

                elif idx == 1:
                    tk.Label(body, text="2/3  Model", bg=BG, fg=FG,
                             font=("Segoe UI", 11, "bold"), anchor="w").pack(
                        fill="x", padx=20, pady=(14, 6)
                    )
                    tk.Label(
                        body,
                        text="You can keep the bundled starter model, or download the recommended one.",
                        bg=BG,
                        fg=MUTED,
                        font=FONT,
                        anchor="w",
                        wraplength=W - 40,
                        justify="left",
                    ).pack(fill="x", padx=20, pady=(0, 10))

                    tk.Label(body, textvariable=recommended_var, bg=BG, fg=FG,
                             font=FONT, anchor="w").pack(fill="x", padx=20, pady=(0, 8))

                    tk.Checkbutton(
                        body,
                        textvariable=use_recommended_text,
                        variable=use_recommended_var,
                        bg=BG,
                        fg=FG,
                        selectcolor=ENTRY_BG,
                        activebackground=BG,
                        activeforeground=FG,
                        font=FONT,
                    ).pack(anchor="w", padx=16, pady=(4, 10))

                    next_btn.config(text="Next")

                else:
                    tk.Label(body, text="3/3  Hotkey", bg=BG, fg=FG,
                             font=("Segoe UI", 11, "bold"), anchor="w").pack(
                        fill="x", padx=20, pady=(14, 6)
                    )
                    tk.Label(
                        body,
                        text="Choose the hotkey you will hold while speaking.",
                        bg=BG,
                        fg=MUTED,
                        font=FONT,
                        anchor="w",
                        wraplength=W - 40,
                        justify="left",
                    ).pack(fill="x", padx=20, pady=(0, 10))

                    tk.Radiobutton(
                        body,
                        text="F8",
                        value="f8",
                        variable=hotkey_var,
                        bg=BG,
                        fg=FG,
                        selectcolor=ENTRY_BG,
                        activebackground=BG,
                        activeforeground=FG,
                        font=FONT,
                    ).pack(anchor="w", padx=16, pady=(2, 2))
                    tk.Radiobutton(
                        body,
                        text="Ctrl+Space",
                        value="ctrl+space",
                        variable=hotkey_var,
                        bg=BG,
                        fg=FG,
                        selectcolor=ENTRY_BG,
                        activebackground=BG,
                        activeforeground=FG,
                        font=FONT,
                    ).pack(anchor="w", padx=16, pady=(2, 10))

                    next_btn.config(text="Finish")

            def go_back():
                if step["index"] > 0:
                    step["index"] -= 1
                    status_var.set("")
                    render_step()

            def go_next():
                idx = step["index"]

                if idx == 0:
                    step["index"] = 1
                    status_var.set("")
                    render_step()
                    return

                if idx == 1:
                    if not use_recommended_var.get():
                        chosen_model["name"] = settings.get("model", "large-v3-turbo")
                        step["index"] = 2
                        status_var.set("")
                        render_step()
                        return

                    rec = recommended_model["name"]
                    if is_model_downloaded(rec):
                        chosen_model["name"] = rec
                        step["index"] = 2
                        status_var.set("")
                        render_step()
                        return

                    status_var.set(f"Downloading {rec}… (this may take a while)")
                    back_btn.config(state="disabled")
                    next_btn.config(state="disabled")

                    def _dl_worker():
                        ok, err = download_model_to_app_dir(rec)

                        def _done():
                            if ok:
                                chosen_model["name"] = rec
                                step["index"] = 2
                                status_var.set("")
                                next_btn.config(state="normal")
                                render_step()
                            else:
                                status_var.set(f"Download failed: {err}")
                                back_btn.config(state="normal")
                                next_btn.config(state="normal")

                        win.after(0, _done)

                    threading.Thread(target=_dl_worker, daemon=True).start()
                    return

                # Finish
                final_settings = dict(settings)
                final_settings.update(
                    {
                        "wizard_completed": True,
                        "hotkey": hotkey_var.get(),
                        "model": chosen_model["name"],
                    }
                )

                status_var.set("Saving settings and loading model…")
                back_btn.config(state="disabled")
                next_btn.config(state="disabled")

                try:
                    save_settings(final_settings)
                except Exception as e:
                    status_var.set(f"Save failed: {e}")
                    win.after(2500, win.destroy)
                    return

                if tray_icon:
                    tray_icon.title = f"Dictation  [{_hotkey_label(final_settings.get('hotkey'))}]"

                def _reload_worker():
                    ok = True
                    err = ""
                    try:
                        requests.post("http://127.0.0.1:8000/reload", timeout=600)
                    except Exception as e:
                        ok = False
                        err = str(e)

                    def _done():
                        if ok and tray_icon:
                            tray_icon.notify("Setup complete.", "Dictation")
                        if ok:
                            win.after(600, win.destroy)
                        else:
                            status_var.set(f"Saved, but backend reload failed: {err}")
                            win.after(2500, win.destroy)

                    win.after(0, _done)

                threading.Thread(target=_reload_worker, daemon=True).start()

            back_btn.config(command=go_back)
            next_btn.config(command=go_next)

            refresh_recommendation_text()
            render_step()
            win.after(80, do_detect_gpu)

        def run_settings_editor():
            def field(parent, label_text, widget_factory):
                tk.Label(parent, text=label_text, bg=BG, fg=MUTED,
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

            model_var = field(
                win,
                "Whisper Model",
                lambda p: make_combo(
                    p,
                    settings.get("model", "large-v3-turbo"),
                    ["base", "small", "medium", "large-v3", "large-v3-turbo"],
                ),
            )
            lang_var = field(
                win,
                "Language Code  (e.g. en, fr, de)",
                lambda p: make_entry(p, settings.get("language", "en")),
            )
            hotkey_var = field(
                win,
                "Hotkey",
                lambda p: make_combo(p, settings.get("hotkey", "f8"), ["f8", "ctrl+space"]),
            )
            duration_var = field(
                win,
                "Record Duration (seconds)",
                lambda p: make_entry(p, settings.get("duration", 5)),
            )

            ttk.Separator(win).pack(fill="x", padx=20, pady=(14, 0))

            llm_var = tk.BooleanVar(value=settings.get("use_llm_rewrite", False))
            tk.Checkbutton(
                win,
                text="Use LLM Rewrite (Ollama)",
                variable=llm_var,
                bg=BG,
                fg=FG,
                selectcolor=ENTRY_BG,
                activebackground=BG,
                activeforeground=FG,
                font=FONT,
            ).pack(anchor="w", padx=16, pady=(10, 0))

            llm_model_var = field(
                win,
                "LLM Model  (e.g. llama3, phi3)",
                lambda p: make_entry(p, settings.get("llm_model", "llama3")),
            )

            status = tk.Label(win, text="", bg=BG, font=FONT)
            status.pack(pady=(6, 0))

            def save():
                try:
                    new_settings = {
                        "wizard_completed": settings.get("wizard_completed", False),
                        "model": model_var.get(),
                        "language": lang_var.get().strip(),
                        "hotkey": hotkey_var.get(),
                        "duration": int(duration_var.get()),
                        "use_llm_rewrite": llm_var.get(),
                        "llm_model": llm_model_var.get().strip(),
                    }
                    save_settings(new_settings)

                    if tray_icon:
                        tray_icon.title = f"Dictation  [{_hotkey_label(new_settings.get('hotkey'))}]"

                    def _reload_worker():
                        try:
                            requests.post("http://127.0.0.1:8000/reload", timeout=600)
                        except Exception:
                            pass

                    threading.Thread(target=_reload_worker, daemon=True).start()

                    status.config(text="Saved!", fg="#4caf50")
                    win.after(1500, win.destroy)
                except Exception as e:
                    status.config(text=f"Error: {e}", fg="#f44336")

            tk.Button(
                win,
                text="Save Settings",
                command=save,
                bg="#1e88e5",
                fg="white",
                activebackground="#1565c0",
                activeforeground="white",
                relief="flat",
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
                pady=8,
            ).pack(fill="x", padx=20, pady=(8, 16))

        if wizard_mode:
            run_first_run_wizard()
        else:
            run_settings_editor()

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
        pystray.MenuItem("Open Releases Page", open_releases),
        pystray.MenuItem("Quit", quit_app),
    )
    tray_icon = pystray.Icon(
        "dictation", make_icon("loading"), "Dictation — Loading model...", menu
    )

    # Show the tray icon immediately in a background thread
    threading.Thread(target=tray_icon.run, daemon=True).start()

    check_for_updates_async()

    print("Starting backend (loading Whisper model)...")
    threading.Thread(target=start_backend, daemon=True).start()

    if not wait_for_backend():
        tray_icon.notify("Failed to load model. Check dictation.log.", "Dictation Error")
        print("Backend failed to start in time. Exiting.")
        sys.exit(1)

    # Model ready — update icon and notify
    tray_icon.icon = make_icon("idle")
    hotkey_label = _hotkey_label(load_settings().get("hotkey", "f8"))
    tray_icon.title = f"Dictation  [{hotkey_label}]"
    tray_icon.notify(f"Ready! Hold {hotkey_label} to dictate.", "Dictation")
    winsound.Beep(660, 100)
    print("Backend ready.")

    if not load_settings().get("wizard_completed", False):
        tray_icon.notify("First run: complete setup.", "Dictation")
        open_settings_window()

    on_press, on_release = make_listener()

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=audio_callback
    )
    stream.start()

    listener = kb.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    print(f"Ready. Hold {hotkey_label} to dictate.")
    threading.Event().wait()  # block until os._exit() from quit_app


if __name__ == "__main__":
    main()
