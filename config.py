import hashlib
import random
from pathlib import Path

import genanki
from rich.console import Console

console = Console()


def get_deterministic_id(text: str) -> int:
    """Generates a consistent integer ID based on a string (e.g., Novel Name)."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (1 << 31)


# --- FILE PATHS & AI ---
NOVELS_ROOT_DIR = Path("./Novels")
TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
SPEAKER_VOICE = "Serena"
TARGET_LANGUAGE = "English"

# --- LLM BACKEND CONFIGURATION ---
BACKENDS = {
    "Ollama": {
        "type": "ollama",
    },
    "LM Studio": {
        "type": "openai",
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
    },
}

# --- MUTABLE RUNTIME STATE ---
_active_backend = "Ollama"
_active_model = None  # Set after fetching models from the backend


def get_backend():
    return BACKENDS[_active_backend]


def get_backend_name():
    return _active_backend


def set_backend(name: str):
    global _active_backend, _active_model
    if name not in BACKENDS:
        raise ValueError(
            f"Unknown backend '{name}'. Choose from: {list(BACKENDS.keys())}"
        )
    _active_backend = name
    _active_model = None  # Reset — user must pick a model for the new backend
    console.print(f"[bold cyan][Config] LLM Backend set to: {name}[/bold cyan]")


def get_llm_model():
    if _active_model is None:
        raise RuntimeError(
            "No model selected. Choose a model before running the pipeline."
        )
    return _active_model


def set_llm_model(model_name: str):
    global _active_model
    _active_model = model_name
    console.print(f"[bold cyan][Config] LLM Model set to: {model_name}[/bold cyan]")


# --- ANKI SETUP ---
MODEL_ID = get_deterministic_id("NixOS_Chinese_Novel_Model_V1")

ANKI_MODEL = genanki.Model(
    MODEL_ID,
    "Chinese Novel Study Model (Audio)",
    fields=[
        {"name": "Chinese"},
        {"name": "Pinyin"},
        {"name": "Literal"},
        {"name": "Natural"},
        {"name": "Audio"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '{{Audio}}<br><h1 style="text-align:center; font-size:40px;">{{Chinese}}</h1>',
            "afmt": '{{FrontSide}}<hr id="answer"><div style="text-align:center; font-size:24px; color:#555;">{{Pinyin}}</div><br><div style="text-align:center; font-size:20px;"><i>"{{Literal}}"</i></div><br><div style="text-align:center; font-size:28px; font-weight:bold;">{{Natural}}</div>',
        }
    ],
    css=".card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }",
)
