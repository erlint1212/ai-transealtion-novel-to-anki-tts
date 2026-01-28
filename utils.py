import re
import ollama
from dataclasses import dataclass
from typing import Optional, Dict, List
from config import LLM_MODEL
from pypinyin import pinyin, Style 

@dataclass
class Chapter:
    novel_name: str
    file_name: str
    content: str
    chapter_number: Optional[int] = None

def extract_chapter_number(file_name: str) -> Optional[int]:
    try: return int(file_name.split('.')[0].split('_')[1])
    except: return None

def chunk_text_into_numbered_lines(text: str, max_chars=400) -> List[Dict[int, str]]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks, current_chunk = [], {}
    current_length, line_idx = 0, 1
    for line in raw_lines:
        if current_length + len(line) > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk, current_length, line_idx = {}, 0, 1
        current_chunk[line_idx] = line
        current_length += len(line)
        line_idx += 1
    if current_chunk: chunks.append(current_chunk)
    return chunks

def get_relevant_glossary(text: str, master_glossary: dict) -> dict:
    """
    Scans the master glossary and returns a mini-glossary 
    containing only the entities found in the current text chunk.
    Supports: characters, places, items, skills.
    """
    relevant = {
        "characters": {},
        "places": {},
        "items": {},
        "skills": {}
    }

    # Iterate through all 4 categories
    categories = ["characters", "places", "items", "skills"]
    
    for category in categories:
        # Check if the category exists in the master file (backward compatibility)
        if category in master_glossary:
            for cn_name, data in master_glossary[category].items():
                if cn_name in text:
                    relevant[category][cn_name] = data
    
    return relevant

def call_llm(system_prompt: str, user_text: str) -> str:
    response = ollama.chat(model=LLM_MODEL, messages=[
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_text}
    ])
    return response['message']['content'].strip()

def parse_numbered_output(llm_output: str, expected_count: int) -> Dict[int, str]:
    results = {i: "" for i in range(1, expected_count + 1)}
    pattern = re.compile(r'^(\d+)[\.\:]\s*(.*)')
    for line in llm_output.splitlines():
        match = pattern.match(line.strip())
        if match:
            idx = int(match.group(1))
            if 1 <= idx <= expected_count: results[idx] = match.group(2).strip()
    return results

def clean_for_tts(text: str) -> str:
    """Sanitizes text to prevent TTS hallucinations on short/mixed-language lines."""
    text = re.sub(r'^(?i)(chapter|ch\.?)\s*\d+\s*[-—:]?\s*', '', text)
    text = re.sub(r'[“”（）《》【】\-—]', '', text)
    text = re.sub(r'？+', '？', text)
    text = re.sub(r'！+', '！', text)
    text = re.sub(r'…+', '…', text)
    text = re.sub(r'\.+', '.', text)
    return text.strip()

def sanitize_filename(text: str) -> str:
    """
    Converts spaces to underscores and removes illegal file system characters.
    Ensures compatibility across Windows, macOS, and Linux.
    """
    # 1. Replace spaces with underscores
    safe_text = text.replace(" ", "_")
    # 2. Remove illegal characters (< > : " / \ | ? *)
    safe_text = re.sub(r'[<>:"/\\|?*]', '', safe_text)
    return safe_text

def generate_pinyin(text: str) -> str:
    """
    Generates Pinyin with tone marks for Chinese text.
    Handles polyphones using pypinyin's built-in dictionary.
    """
    # style=Style.TONE ensures we get "hǎo" instead of "hao3" or "hao"
    # heteronym=False picks the most likely pronunciation based on context
    pinyin_list = pinyin(text, style=Style.TONE, heteronym=False)
    
    # pinyin() returns a list of lists (e.g. [['nǐ'], ['hǎo']]).
    # We flatten it and join with spaces for readability.
    return " ".join([item[0] for item in pinyin_list])
