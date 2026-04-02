import json
from typing import Dict

from config import TARGET_LANGUAGE

# Appended to all translation prompts to suppress thinking-mode artifacts
_OUTPUT_RULES = """
CRITICAL OUTPUT RULES:
- Output ONLY the numbered lines. Nothing else.
- Do NOT include any reasoning, analysis, drafting steps, or markdown headers.
- Do NOT wrap your output in code blocks or any other formatting.
- Every line of output MUST start with its number followed by a period (e.g., "1. ", "2. ").
"""


def prompt_json():
    return """You are an expert Novel Entity Extractor.
Analyze the provided Chinese text and extract:
1. Characters (Names, Pronouns)
2. Place Names (Locations)
3. Items (Unique objects, artifacts, potions)
4. Skills (Techniques, spells, abilities, usually in brackets like 【...】 or quotes)

Return ONLY a JSON object. No reasoning, no markdown, no explanation.
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
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ").
{_OUTPUT_RULES}"""


def prompt_literal(sub_glossary: Dict):
    return f"""Translate the NUMBERED Chinese lines to EXTREMELY LITERAL word-for-word English.
Preserve Chinese grammar and word order. Do NOT rephrase into natural English.

EXAMPLE:
Chinese: 她的眼睛闪烁着不可思议之色
WRONG (too natural): Her eyes flashed with disbelief.
CORRECT (literal): Her eyes flickered with impossible-to-believe color.

CRITICAL: Use these specific English names: {json.dumps(sub_glossary, ensure_ascii=False)}
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ").
{_OUTPUT_RULES}"""


def prompt_pinyin(sub_glossary: Dict):
    return f"""Transliterate the NUMBERED Chinese lines into Pinyin with tone marks.
CRITICAL: Use these specific Pinyin spellings for these entities: {json.dumps(sub_glossary, ensure_ascii=False)}
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ").
{_OUTPUT_RULES}"""


def prompt_emotion():
    return f"""You are an audiobook director. Analyze the NUMBERED Chinese lines and determine the vocal emotion/style for each line.

RULES:
1. Output ONLY a 1-4 word instruction in English (e.g., "Calm narrative", "Angry shouting", "Whispering fearfully", "Sarcastic laugh").
2. If it is just description, use "Calm narrative" or "Suspenseful narrative".
3. You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ").
{_OUTPUT_RULES}"""
