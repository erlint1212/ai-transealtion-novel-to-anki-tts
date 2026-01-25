import ollama
import genanki
import random
import os
import json
import logging
import time
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from ebooklib import epub

console = Console()

# --- SETUP VERBOSE LOGGING ---
logging.basicConfig(
    filename='parser.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# --- CONFIGURATION ---
MODEL_NAME = "qwen2.5:14b-instruct-q5_K_M"
NOVELS_ROOT_DIR = Path("./Novels")
TARGET_LANGUAGE = "English"

# --- ANKI SETUP ---
DECK_ID = random.randrange(1 << 30, 1 << 31)
MODEL_ID = random.randrange(1 << 30, 1 << 31)

my_model = genanki.Model(
    MODEL_ID,
    'Chinese Novel Study Model',
    fields=[{'name': 'Chinese'}, {'name': 'Pinyin'}, {'name': 'Literal'}, {'name': 'Natural'}],
    templates=[{
        'name': 'Card 1',
        'qfmt': '<h1 style="text-align:center; font-size:40px;">{{Chinese}}</h1>',
        'afmt': '{{FrontSide}}<hr id="answer"><div style="text-align:center; font-size:24px; color:#555;">{{Pinyin}}</div><br><div style="text-align:center; font-size:20px;"><i>"{{Literal}}"</i></div><br><div style="text-align:center; font-size:28px; font-weight:bold;">{{Natural}}</div>',
    }],
    css='.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }'
)

@dataclass
class Chapter:
    novel_name: str
    file_name: str
    content: str
    chapter_number: Optional[int] = None

# --- SPECIALIZED MICRO-PROMPTS ---

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
    "文尼": {{
      "pinyin": "Wénní",
      "english_name": "Vinnie",
      "pronoun": "he/him"
    }},
    "艾茜菲丝": {{
      "pinyin": "Àiqīfēisī",
      "english_name": "Acephice",
      "pronoun": "she/her"
    }}
  }},
  "places": {{
    "奥兰迪亚": {{
      "pinyin": "Àolándìyà",
      "english_name": "Orlandia"
    }}
  }}
}}

Now process the user text."""

def prompt_natural(glossary: Dict):
    return f"""Translate the NUMBERED Chinese lines to natural {TARGET_LANGUAGE}.
Convert imperial to metric. Use names from this glossary: {json.dumps(glossary, ensure_ascii=False)}
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""

def prompt_literal():
    return """Translate the NUMBERED Chinese lines to EXTREMELY LITERAL word-for-word English.
Preserve Chinese grammar. 
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""

def prompt_pinyin():
    return """Transliterate the NUMBERED Chinese lines into Pinyin with tone marks.
You MUST output the exact same number of lines. Start each line with its number (e.g., "1. ")."""

# --- HELPER FUNCTIONS ---
def chunk_text_into_numbered_lines(text, max_chars=400):
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks = []
    current_chunk = {}
    current_length = 0
    line_idx = 1
    
    for line in raw_lines:
        if current_length + len(line) > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = {}
            current_length = 0
            line_idx = 1
            
        current_chunk[line_idx] = line
        current_length += len(line)
        line_idx += 1
        
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

def extract_chapter_number(file_name: str) -> Optional[int]:
    try: return int(file_name.split('.')[0].split('_')[1])
    except: return None

def call_llm(system_prompt, user_text):
    response = ollama.chat(model=MODEL_NAME, messages=[
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_text}
    ])
    return response['message']['content'].strip()

def parse_numbered_output(llm_output, expected_count):
    results = {i: "" for i in range(1, expected_count + 1)}
    pattern = re.compile(r'^(\d+)[\.\:]\s*(.*)')
    for line in llm_output.splitlines():
        match = pattern.match(line.strip())
        if match:
            idx = int(match.group(1))
            content = match.group(2).strip()
            if 1 <= idx <= expected_count:
                results[idx] = content
    return results

# --- MAIN ENGINE ---
def process_novel(novel_dir: Path):
    novel_name = novel_dir.name
    raw_dir = novel_dir / "01_Raw_Text"
    trans_dir = novel_dir / "02_Translated"
    trans_dir.mkdir(exist_ok=True)
    
    glossary_file = novel_dir / "glossary.json"
    glossary = json.loads(glossary_file.read_text()) if glossary_file.exists() else {"characters": {}, "places": {}}

    my_deck = genanki.Deck(DECK_ID, f'{novel_name} Vocab & Sentences')
    book = epub.EpubBook()
    book.set_title(novel_name)
    book.set_language('en')
    book_chapters = []

    epub_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content="""
        .study-block { margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid #eee; }
        .cn { font-size: 1.4em; font-weight: bold; margin: 0; color: #000; }
        .py { font-size: 1em; color: #555; margin: 0; font-family: monospace; }
        .lit { font-size: 1em; font-style: italic; color: #666; margin: 0; }
        .en { font-size: 1.1em; font-weight: bold; color: #1a1a1a; margin: 0; }
        h1 { text-align: center; margin-bottom: 30px; font-size: 2em; }
    """)
    book.add_item(epub_css)

    chapters = []
    for txt_file in sorted(raw_dir.glob("*.txt")):
        content = txt_file.read_text(encoding='utf-8')
        chapters.append(Chapter(novel_name, txt_file.name, content, extract_chapter_number(txt_file.name)))

    for chapter in chapters:
        console.print(f"\n[bold]Processing Chapter: {chapter.file_name}[/bold]")
        chunks = chunk_text_into_numbered_lines(chapter.content)
        
        full_translated_text = ""
        epub_body_html = ""
        chapter_title_en = chapter.file_name  # Fallback title
        cards_added_in_chapter = 0
        
        for i, chunk_dict in enumerate(chunks):
            chunk_size = len(chunk_dict)
            chunk_start_time = time.time()
            numbered_input = "\n".join([f"{idx}. {text}" for idx, text in chunk_dict.items()])
            
            with Progress(SpinnerColumn(), TextColumn(f"[blue]Processing Chunk {i+1}/{len(chunks)} ({chunk_size} lines)..."), transient=True) as progress:
                progress.add_task("translating", total=None)
                
                # --- PASS 1: JSON Extraction (Pure Extraction) ---
                t0 = time.time()
                res_json = call_llm(prompt_json(), numbered_input) # Removed glossary from prompt
                time_json = time.time() - t0
                
                # --- PYTHON MERGE LOGIC ---
                try:
                    json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
                    new_entities = json.loads(json_str)
                    
                    # Merge Characters: Only add if the key doesn't already exist
                    for char_name, char_data in new_entities.get("characters", {}).items():
                        if char_name not in glossary["characters"]:
                            glossary["characters"][char_name] = char_data
                            
                    # Merge Places: Only add if the key doesn't already exist
                    for place_name, place_data in new_entities.get("places", {}).items():
                        if place_name not in glossary["places"]:
                            glossary["places"][place_name] = place_data
                            
                except Exception:
                    pass

                # --- PASS 2: Natural English (Passes the updated glossary) ---
                t1 = time.time()
                res_nat_raw = call_llm(prompt_natural(glossary), numbered_input)
                nat_dict = parse_numbered_output(res_nat_raw, chunk_size)
                time_nat = time.time() - t1
                
                # --- PASS 3: Literal English ---
                t2 = time.time()
                res_lit_raw = call_llm(prompt_literal(), numbered_input)
                lit_dict = parse_numbered_output(res_lit_raw, chunk_size)
                time_lit = time.time() - t2
                
                # --- PASS 4: Pinyin ---
                t3 = time.time()
                res_py_raw = call_llm(prompt_pinyin(), numbered_input)
                py_dict = parse_numbered_output(res_py_raw, chunk_size)
                time_py = time.time() - t3

            # COMBINE DATA
            cards_in_chunk = 0
            for idx in range(1, chunk_size + 1):
                cn = chunk_dict[idx]
                nat = nat_dict[idx]
                lit = lit_dict[idx]
                py = py_dict[idx]

                if i == 0 and idx == 1:
                    chapter_title_en = nat 
                    epub_body_html += f"<h1>{nat}</h1>\n"

                full_translated_text += nat + "\n"

                note = genanki.Note(model=my_model, fields=[cn, py, lit, nat], tags=[novel_name, f"Ch_{chapter.chapter_number}"])
                my_deck.add_note(note)
                
                epub_body_html += f"""
                <div class="study-block">
                    <p class="cn">{cn}</p>
                    <p class="py">{py}</p>
                    <p class="lit">"{lit}"</p>
                    <p class="en">{nat}</p>
                </div>
                """
                cards_in_chunk += 1
                cards_added_in_chapter += 1

            chunk_total_time = time.time() - chunk_start_time
            console.print(f"[dim]Chunk {i+1} done in {chunk_total_time:.1f}s -> Mapped {cards_in_chunk}/{chunk_size} lines.[/dim]")

        console.print(f"[green]✓ Chapter complete: '{chapter_title_en}' ({cards_added_in_chapter} cards)[/green]")

        (trans_dir / chapter.file_name).write_text(full_translated_text, encoding='utf-8')
        
        epub_ch = epub.EpubHtml(title=chapter_title_en, file_name=f"{chapter.file_name}.xhtml", lang='en')
        epub_ch.content = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_body_html}</body></html>"
        epub_ch.add_item(epub_css)
        book.add_item(epub_ch)
        book_chapters.append(epub_ch)

    # Save glossary to disk at the end of the chapter
    glossary_file.write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')
    genanki.Package(my_deck).write_to_file(str(novel_dir / f"{novel_name}.apkg"))
    
    book.toc = book_chapters
    book.add_item(epub.EpubNcx()); book.add_item(epub.EpubNav())
    book.spine = ['nav'] + book_chapters
    epub.write_epub(str(novel_dir / f"{novel_name}.epub"), book)

    console.print(f"[bold green]✓ Done! Created .apkg, .epub, and updated glossary in {novel_dir}[/bold green]")

def main():
    if not NOVELS_ROOT_DIR.exists(): return
    for novel_dir in NOVELS_ROOT_DIR.iterdir():
        if novel_dir.is_dir() and (novel_dir / "01_Raw_Text").exists():
            process_novel(novel_dir)

if __name__ == "__main__":
    main()
