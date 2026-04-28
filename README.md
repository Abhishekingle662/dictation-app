# Dictation

A local, GPU-accelerated dictation app for Windows. Hold a hotkey, speak, release — your words are transcribed and pasted wherever your cursor is. Everything runs on your machine; no cloud, no subscription.

## What's new — packaging & distribution refactor

- **Freeze-safe paths & imports** — `run.py` uses `app_paths.py` for settings, logs, and model storage under `%LOCALAPPDATA%\Dictation\`. Imports are structured so PyInstaller one-file builds work without path hacks.
- **First-run wizard** — on first launch the settings window opens automatically, detects your GPU, optionally downloads the recommended model, and lets you choose your hotkey before anything starts.
- **Update checker** — on startup, checks GitHub Releases in the background. If a newer version is found, a tray notification appears and a new tray action opens the releases page. Override the repo with the `DICTATION_GITHUB_REPO` environment variable.
- **Backend alignment** — `main.py` reads settings and caches models via `app_paths.py`, and automatically falls back to CPU (`int8`) when CUDA is unavailable.
- **Packaging artifacts** — added `dictation.spec` (PyInstaller), `build.ps1` (one-file exe build script), `installer/Dictation.iss` (Inno Setup), and `tools/prefetch_model.py` (pre-bundles a model for the installer).

---

---

## Features

- **Hold F8 or Ctrl+Space** to record, release to transcribe and paste
- **Whisper large-v3-turbo** (default) running locally via faster-whisper
- **Optional LLM rewrite** — cleans up punctuation and grammar using a local Ollama model
- **System tray app** — grey icon while loading, green when ready, red while recording
- **Native settings window** — change model, language, hotkey, duration without touching any files
- **First-run wizard** — detect GPU, optionally download a recommended model, choose hotkey
- **Update checker** — checks GitHub Releases on startup and offers an “Open Releases Page” action
- **Windows installer** (Inno Setup) with optional auto-start on login

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                      run.py                         │
│                  (single process)                   │
│                                                     │
│  ┌─────────────┐   ┌────────────┐  ┌─────────────┐ │
│  │  pystray    │   │  pynput    │  │  sounddevice│ │
│  │  tray icon  │   │  hotkey    │  │  mic input  │ │
│  └─────────────┘   └────────────┘  └─────────────┘ │
│                          │                │         │
│              hold hotkey │                │ PCM     │
│                          ▼                ▼         │
│                   ┌─────────────────────────┐       │
│                   │   recording state +     │       │
│                   │   audio buffer          │       │
│                   └────────────┬────────────┘       │
│                                │ on release         │
│                                ▼                    │
│                   ┌─────────────────────────┐       │
│                   │  FastAPI backend thread │       │
│                   │  POST /transcribe/file  │       │
│                   │                         │       │
│                   │  faster-whisper         │       │
│                   │  Whisper large-v3-turbo │       │
│                   │  CUDA / GPU             │       │
│                   └────────────┬────────────┘       │
│                                │ transcript text    │
│                                ▼                    │
│                   ┌─────────────────────────┐       │
│                   │  (optional) Ollama LLM  │       │
│                   │  POST localhost:11434   │       │
│                   └────────────┬────────────┘       │
│                                │ refined text       │
│                                ▼                    │
│                   ┌─────────────────────────┐       │
│                   │  pyperclip + Ctrl+V     │       │
│                   │  paste to active window │       │
│                   └─────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

Everything runs inside a single Python process. The FastAPI server runs on a background thread. The tray icon runs on its own thread. The main thread blocks until quit.

---

## Data Flow

1. **User holds hotkey** (F8 or Ctrl+Space) → `pynput` fires `on_press`
2. **Recording starts** — `sounddevice.InputStream` begins appending PCM chunks to a buffer; tray icon turns red
3. **User releases hotkey** → `on_release` fires, recording stops, tray turns green
4. **Audio is encoded** as a WAV in memory (`scipy.io.wavfile`) and sent via HTTP to the local FastAPI backend (`POST /transcribe/file`)
5. **Whisper transcribes** the audio using `faster-whisper` on the GPU
6. *(Optional)* **Ollama refines** the raw transcript — fixes punctuation, capitalisation, grammar
7. **Text is pasted** — copied to clipboard via `pyperclip`, then `Ctrl+V` is simulated into the active window

Settings changes (model, language, etc.) are written per-user under `%LOCALAPPDATA%\Dictation\settings.json` (see `app_paths.py`). A `POST /reload` call to the backend hot-swaps the Whisper model without restarting the process.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Entry point | Python `run.py` | Orchestrates all components |
| Transcription | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CTranslate2-based Whisper inference |
| Model | Whisper (default: large-v3-turbo) | Speech-to-text |
| GPU acceleration | CUDA + CTranslate2 float16 | Low-latency inference on NVIDIA GPU |
| HTTP server | FastAPI + Uvicorn | Hosts the transcription endpoint |
| Hotkeys | pynput | Global keyboard listener |
| Audio capture | sounddevice | Microphone input stream |
| Audio encoding | scipy.io.wavfile | PCM → WAV in memory |
| Clipboard paste | pyperclip + pynput | Paste transcribed text |
| System tray | pystray + Pillow | Tray icon with state colours |
| Settings UI | tkinter (ttk) | Native settings window |
| LLM rewrite | [Ollama](https://ollama.com) (optional) | Local LLM post-processing |
| Installer | Windows `.bat` + `.vbs` | Desktop shortcut + startup entry |

---

## Requirements

- Windows 10/11
- Python 3.10+
- NVIDIA GPU with CUDA drivers
- [Ollama](https://ollama.com) *(optional, for LLM rewrite)*

---

## Setup

### Run from source (dev)

```bash
# 1. Clone the repo
git clone https://github.com/Abhishekingle662/dictation.git
cd dictation

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install as a desktop app (creates shortcut + startup entry)
python run.py
```

The first time you run it, the settings window opens as a first-run wizard.

### Build EXE + installer

- Build the one-file exe: `powershell -ExecutionPolicy Bypass -File .\build.ps1`
- (Optional) Bundle the starter model for the installer: `python .\tools\prefetch_model.py --model large-v3-turbo`
- Compile the installer: open [installer/Dictation.iss](installer/Dictation.iss) in Inno Setup and build, or run `ISCC.exe installer\Dictation.iss`

---

## Running the App

### First time

```bash
cd c:\path\to\dictation
.venv\Scripts\activate
python run.py
```

The first-run wizard opens automatically. It will:
1. Detect whether a CUDA-capable GPU is present
2. Recommend and optionally download the right Whisper model
3. Ask you to choose a hotkey (F8 or Ctrl+Space)

After you confirm, the wizard closes and the app starts normally.

---

### Every day (after first-time setup)

**Option A — Desktop shortcut (recommended)**

Run `install.bat` once to create a desktop shortcut and a Windows startup entry:

```bash
install.bat
```

From then on, double-click the **Dictation** shortcut on your desktop. The app also launches automatically every time you log in to Windows — no terminal needed.

**Option B — From the terminal**

```bash
cd c:\path\to\dictation
.venv\Scripts\activate
python run.py
```

---

### What to expect on startup

| Time | Tray icon | What's happening |
|---|---|---|
| 0–2 sec | Grey mic appears | App launched, backend starting |
| 15–30 sec | Still grey | Whisper model loading into GPU VRAM |
| Ready | Green mic + notification | Model loaded, hotkeys active |

> **Tip:** The exact load time depends on your GPU and which model is configured. `large-v3` takes ~20–30 seconds on first load; subsequent loads are faster once the model is cached.

---

### Checking logs

If something goes wrong and no tray icon appears, check the log file:

```
%LOCALAPPDATA%\Dictation\dictation.log
```

---

## Usage

| Action | Result |
|---|---|
| Hold your configured hotkey (**F8** or **Ctrl+Space**) | Start recording |
| Release hotkey | Transcribe and paste |
| Right-click tray icon → **Open Settings** | Open settings window |
| Right-click tray icon → **Quit** | Exit the app |

---

## Settings

| Setting | Default | Description |
|---|---|---|
| Whisper Model | `large-v3-turbo` | Model size (larger = more accurate, slower to load) |
| Language Code | `en` | BCP-47 language code |
| Hotkey | `f8` | `f8` or `ctrl+space` |
| Record Duration | `5` | Max recording length in seconds |
| Use LLM Rewrite | off | Post-process transcript with a local Ollama model |
| LLM Model | `llama3` | Any model pulled via `ollama pull <name>` |

---

## Project Structure

```
dictation/
├── run.py              # Main entry point — tray, hotkeys, recording, paste
├── app_paths.py         # App-data paths (settings/logs/models) for frozen builds
├── backend/
│   ├── app/
│   │   └── main.py    # FastAPI server — Whisper inference + /reload endpoint
│   └── requirements.txt
├── agent/
│   └── agent.py       # Standalone agent (legacy, superseded by run.py)
├── dictation.spec       # PyInstaller spec (one-file build)
├── build.ps1            # Build script for the exe
├── installer/
│   └── Dictation.iss    # Inno Setup installer script
├── tools/
│   └── prefetch_model.py # Helper to download models for bundling
└── requirements.txt    # All Python dependencies
```
