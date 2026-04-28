from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

APP_NAME = "Dictation"
ENV_DATA_DIR = "DICTATION_DATA_DIR"


def get_data_dir() -> Path:
    """Return the directory where Dictation stores runtime data.

    Default: %LOCALAPPDATA%\\Dictation
    Override: set the env var DICTATION_DATA_DIR.
    """

    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser().resolve()

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return (Path(base) / APP_NAME).resolve()

    # Very rare on Windows, but keep a sane fallback
    return (Path.home() / f".{APP_NAME.lower()}").resolve()


def ensure_data_dirs() -> Path:
    root = get_data_dir()
    (root / "models").mkdir(parents=True, exist_ok=True)
    return root


def get_models_dir() -> Path:
    return ensure_data_dirs() / "models"


def get_settings_path() -> Path:
    return ensure_data_dirs() / "settings.json"


def get_log_path() -> Path:
    return ensure_data_dirs() / "dictation.log"


def default_settings() -> Dict[str, Any]:
    # Starter model should match what we bundle in the installer.
    return {
        "wizard_completed": False,
        "model": "large-v3-turbo",
        "language": "en",
        "hotkey": "f8",  # "f8" | "ctrl+space"
        "duration": 5,
        "use_llm_rewrite": False,
        "llm_model": "llama3",
    }


def load_settings() -> Dict[str, Any]:
    path = get_settings_path()
    settings = default_settings()

    if path.exists():
        try:
            settings.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            # Corrupt settings: keep defaults but don't crash the app
            pass

    # Ensure required keys exist
    for key, value in default_settings().items():
        settings.setdefault(key, value)

    return settings


def save_settings(new_settings: Dict[str, Any]) -> None:
    path = get_settings_path()
    merged = default_settings()
    merged.update(new_settings or {})
    path.write_text(json.dumps(merged, indent=4), encoding="utf-8")
