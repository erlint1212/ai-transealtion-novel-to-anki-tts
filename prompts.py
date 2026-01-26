import json
from typing import Dict
from config import TARGET_LANGUAGE

def prompt_json():
    return f"""You are a precise data extraction AI. Extract ALL proper nouns (Characters, Places, Clans) from the text.
RULES:
1. Output ONLY a valid JSON object. Do not include markdown block ticks.
2. 'pinyin' MUST include tone marks (e.g., "Wénní").
3. 'english_name' MUST be a natural English translation or phonetic equivalent (e.g., "Vinnie").
4. 'pronoun' MUST be in the format "he/him", "she/her", "it/its", or "they/them" based on context.

EXAMPLE INPUT:
文尼在奥兰迪亚遇到了艾茜菲丝。

EXAMPLE JSON OUTPUT:
{{
  "characters": {{
    "文尼": {{ "pinyin": "Wénní", "english_name": "Vinnie", "pronoun": "he/him" }},
    "艾茜菲丝": {{ "pinyin": "Àiqīfēisī", "english_name": "Aquisis", "pronoun": "she/her" }}
  }},
  "places": {{ "奥兰迪亚": {{ "pinyin": "Àolándìyà", "english_name": "Orlandia" }} }}
}}
Now process the user text."""

def prompt_natural(sub_glossary: Dict):
    return f"""Translate the NUMBERED Chinese lines to natural {TARGET_LANGUAGE}.
Convert imperial to metric. 
CRITICAL: Use these specific English names for these entities: {json.dumps(sub_glossary, ensure_ascii=False)}
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""

def prompt_literal(sub_glossary: Dict):
    return f"""Translate the NUMBERED Chinese lines to EXTREMELY LITERAL word-for-word English.
Preserve Chinese grammar. 
CRITICAL: Use these specific English names for these entities: {json.dumps(sub_glossary, ensure_ascii=False)}
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""

def prompt_pinyin(sub_glossary: Dict):
    return f"""Transliterate the NUMBERED Chinese lines into Pinyin with tone marks.
CRITICAL: Use these specific Pinyin spellings for these entities: {json.dumps(sub_glossary, ensure_ascii=False)}
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""

def prompt_emotion():
    return f"""You are an audiobook director. Analyze the NUMBERED Chinese lines and determine the vocal emotion/style for each line.

RULES:
1. Output ONLY a 1-4 word instruction in English (e.g., "Calm narrative", "Angry shouting", "Whispering fearfully", "Sarcastic laugh").
2. If it is just description, use "Calm narrative" or "Suspenseful narrative".
3. You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""
