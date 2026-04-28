import io
import time
import numpy as np
import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from faster_whisper import WhisperModel
import scipy.io.wavfile as wavfile

try:
    # Preferred: shared app-data paths (works for PyInstaller one-file builds)
    from app_paths import load_settings, get_models_dir
except Exception:  # pragma: no cover
    # Fallback for running this module directly from backend/app/
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from app_paths import load_settings, get_models_dir

app = FastAPI(title="Local Dictation Backend")

initial_settings = load_settings()

model: WhisperModel | None = None

def reload_model(settings: dict):
    global model
    model_name = settings.get("model", "large-v3-turbo")
    device = "cpu"
    compute_type = "int8"

    try:
        import ctranslate2

        if int(ctranslate2.get_cuda_device_count()) > 0:
            device = "cuda"
            compute_type = "float16"
    except Exception:
        # No CUDA runtime / not installed; fall back to CPU.
        pass

    print(f"Loading Whisper Model ({model_name}) on {device} ({compute_type})...")
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=str(get_models_dir()),
    )
    print("Model loaded.")

reload_model(initial_settings)

# Ollama local Endpoint
OLLAMA_URL = "http://localhost:11434/api/generate"

def refine_text_with_llm(raw_text: str, model_name="llama3") -> str:
    """Uses a local Ollama model to clean up dictated text."""
    prompt = (
        "You are an AI dictation assistant. Your task is to clean up raw speech-to-text transcriptions. "
        "Fix punctuation, capitalization, and minor grammatical errors, but PRESERVE the speaker's original "
        "meaning, context, and tone. DO NOT add conversational filler or explain your output. JUST output "
        "the corrected text.\n\n"
        f"Raw Transcription:\n{raw_text}"
    )
    
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0}
        }, timeout=10)
        response.raise_for_status()
        return response.json().get("response", raw_text).strip()
    except Exception as e:
        print(f"LLM refine failed: {e}")
        # Fallback to the raw text if LLM fails (e.g. Ollama isn't running)
        return raw_text

class TranscribeResponse(BaseModel):
    text: str
    processing_time: float

@app.post("/transcribe/file", response_model=TranscribeResponse)
async def transcribe_file(
    file: UploadFile = File(...),
    language: str = Form("en"),
    beam_size: int = Form(5),
    temperature: float = Form(0.0),
    vad_filter: bool = Form(True),
    use_llm_rewrite: bool = Form(False),
    llm_model: str = Form("llama3")
):
    try:
        start_time = time.time()
        
        # Read the uploaded audio bytes
        audio_bytes = await file.read()
        
        # Process the audio with faster-whisper (faster-whisper accepts file streams/bytes)
        # We can pass an io.BytesIO buffer to faster-whisper
        audio_stream = io.BytesIO(audio_bytes)
        
        segments, info = model.transcribe(
            audio_stream,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
            temperature=temperature,
        )
        
        text = " ".join(s.text.strip() for s in segments)
        
        # Optional post-processing with LLM
        if use_llm_rewrite and text:
            print(f"Refining text with {llm_model}...")
            text = refine_text_with_llm(text, model_name=llm_model)

        end_time = time.time()
        
        return TranscribeResponse(
            text=text.strip(),
            processing_time=round(end_time - start_time, 3)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reload")
async def reload_settings():
    settings = load_settings()
    reload_model(settings)
    return {"success": True, "model": settings.get("model", "large-v3-turbo")}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
