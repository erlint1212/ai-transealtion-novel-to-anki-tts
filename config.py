import random
from pathlib import Path
import genanki
from rich.console import Console

console = Console()

# --- FILE PATHS ---
NOVELS_ROOT_DIR = Path("./Novels")

# --- AI MODELS ---
LLM_MODEL = "qwen2.5:14b-instruct-q5_K_M"
TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice" 
SPEAKER_VOICE = "Serena" 
TARGET_LANGUAGE = "English"

# --- ANKI SETUP ---
DECK_ID = random.randrange(1 << 30, 1 << 31)
MODEL_ID = random.randrange(1 << 30, 1 << 31)

ANKI_MODEL = genanki.Model(
    MODEL_ID,
    'Chinese Novel Study Model (Audio)',
    fields=[{'name': 'Chinese'}, {'name': 'Pinyin'}, {'name': 'Literal'}, {'name': 'Natural'}, {'name': 'Audio'}],
    templates=[{
        'name': 'Card 1',
        'qfmt': '{{Audio}}<br><h1 style="text-align:center; font-size:40px;">{{Chinese}}</h1>',
        'afmt': '{{FrontSide}}<hr id="answer"><div style="text-align:center; font-size:24px; color:#555;">{{Pinyin}}</div><br><div style="text-align:center; font-size:20px;"><i>"{{Literal}}"</i></div><br><div style="text-align:center; font-size:28px; font-weight:bold;">{{Natural}}</div>',
    }],
    css='.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }'
)
