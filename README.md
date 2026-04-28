# Dictation

A local, GPU-accelerated dictation app for Windows. Hold a hotkey, speak, release — your words are transcribed and pasted wherever your cursor is. Everything runs on your machine; no cloud, no subscription.

---

## Features

- **Hold F8 or Ctrl+Space** to record, release to transcribe and paste
- **Whisper large-v3** running locally on GPU via faster-whisper
- **Optional LLM rewrite** — cleans up punctuation and grammar using a local Ollama model
- **System tray app** — grey icon while loading, green when ready, red while recording
- **Native settings window** — change model, language, hotkey, duration without touching any files
- **Auto-starts on Windows login** after running `install.bat` once

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
│                   │  Whisper large-v3       │       │
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

Settings changes (model, language, etc.) are written to `settings.json`. A `POST /reload` call to the backend hot-swaps the Whisper model without restarting the process.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Entry point | Python `run.py` | Orchestrates all components |
| Transcription | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CTranslate2-based Whisper inference |
| Model | Whisper large-v3 (OpenAI) | Speech-to-text |
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
install.bat
```

After `install.bat`, double-click the **Dictation** shortcut on your desktop. The grey tray icon appears immediately; it turns green with a notification once the model has loaded (~15–30 seconds).

---

## Usage

| Action | Result |
|---|---|
| Hold **F8** | Start recording |
| Hold **Ctrl+Space** | Start recording |
| Release hotkey | Transcribe and paste |
| Right-click tray icon → **Open Settings** | Open settings window |
| Right-click tray icon → **Quit** | Exit the app |

---

## Settings

| Setting | Default | Description |
|---|---|---|
| Whisper Model | `large-v3` | Model size (larger = more accurate, slower to load) |
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
├── backend/
│   ├── app/
│   │   └── main.py    # FastAPI server — Whisper inference + /reload endpoint
│   └── requirements.txt
├── agent/
│   └── agent.py       # Standalone agent (legacy, superseded by run.py)
├── settings.json       # User configuration (read/written at runtime)
├── launch.vbs          # Silent launcher (no terminal window)
├── install.bat         # One-time installer — desktop + startup shortcuts
└── requirements.txt    # All Python dependencies
```
