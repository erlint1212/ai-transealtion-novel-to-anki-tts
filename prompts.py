import json
from typing import Dict
from config import TARGET_LANGUAGE

def prompt_json():
    return """
    You are an expert Novel Entity Extractor. 
    Analyze the provided Chinese text and extract:
    1. Characters (Names, Pronouns)
    2. Place Names (Locations)
    3. Items (Unique objects, artifacts, potions)
    4. Skills (Techniques, spells, abilities, usually in brackets like 【...】 or quotes)

    Return ONLY a JSON object. Do not include markdown formatting.
    Format:
    {
        "characters": {
            "ChineseName": { "pinyin": "Pinyin", "english_name": "EnglishName", "pronoun": "he/she/it/they" }
        },
        "places": {
            "ChineseName": { "pinyin": "Pinyin", "english_name": "EnglishName" }
        },
        "items": {
            "ChineseName": { "pinyin": "Pinyin", "english_name": "EnglishName" }
        },
        "skills": {
            "ChineseName": { "pinyin": "Pinyin", "english_name": "EnglishName" }
        }
    }
    """

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
