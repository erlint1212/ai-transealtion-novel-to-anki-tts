import ollama
import genanki
import random
import os
import json
import logging
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

# --- DATACLASSES ---
@dataclass
class Chapter:
    novel_name: str
    file_name: str
    content: str
    chapter_number: Optional[int] = None

# --- SPECIALIZED MICRO-PROMPTS ---

def prompt_natural(glossary: Dict):
    return f"""Translate the Chinese text to natural {TARGET_LANGUAGE} line-by-line.
Convert imperial to metric. 
Use the 'english_name' from this glossary for characters/places: {json.dumps(glossary, ensure_ascii=False)}
DO NOT output anything else. Just the line-by-line translation."""

def prompt_literal():
    return """Translate the Chinese text to EXTREMELY LITERAL word-for-word English line-by-line. 
Preserve the Chinese grammatical structure even if it sounds robotic in English.
DO NOT output anything else. Just the line-by-line literal translation."""

def prompt_pinyin():
    return """Transliterate the Chinese text into Pinyin with tone marks line-by-line.
DO NOT translate. DO NOT output Chinese characters. Just the Pinyin."""

def prompt_json(glossary: Dict):
    return f"""Extract ALL proper nouns (Characters and Places) from the text.
Compare against this existing glossary: {json.dumps(glossary, ensure_ascii=False)}
Output ONLY a JSON object containing NEW entities NOT in the glossary.
Format: {{"characters": {{"Name": {{"pinyin": "", "english_name": "", "pronoun": ""}}}}, "places": {{"Name": {{"pinyin": "", "english_name": ""}}}}}}
Do not include markdown blocks, just the raw JSON."""

# --- HELPER FUNCTIONS ---
def chunk_text(text, max_chars=400):
    lines = text.splitlines()
    chunks, current_chunk = [], []
    current_length = 0
    for line in lines:
        line = line.strip()
        if not line: continue
        if current_length + len(line) > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk, current_length = [], 0
        current_chunk.append(line)
        current_length += len(line)
    if current_chunk: chunks.append("\n".join(current_chunk))
    return chunks

def extract_chapter_number(file_name: str) -> Optional[int]:
    try: return int(file_name.split('.')[0].split('_')[1])
    except: return None

def call_llm(system_prompt, user_text):
    """Generic function to call Ollama."""
    response = ollama.chat(model=MODEL_NAME, messages=[
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_text}
    ])
    return response['message']['content'].strip()

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
    """)
    book.add_item(epub_css)

    chapters = []
    for txt_file in sorted(raw_dir.glob("*.txt")):
        content = txt_file.read_text(encoding='utf-8')
        chapters.append(Chapter(novel_name, txt_file.name, content, extract_chapter_number(txt_file.name)))

    for chapter in chapters:
        console.print(f"\n[bold]Processing Chapter: {chapter.file_name}[/bold]")
        chunks = chunk_text(chapter.content)
        
        full_translated_text = ""
        epub_chapter_html = f"<h1>{chapter.file_name}</h1>"
        cards_added_in_chapter = 0
        
        for i, chunk in enumerate(chunks):
            chunk_lines = chunk.split('\n')
            
            with Progress(SpinnerColumn(), TextColumn(f"[blue]Running 4-Pass Pipeline on chunk {i+1}/{len(chunks)}..."), transient=True) as progress:
                progress.add_task("translating", total=None)
                
                # --- PASS 1: Natural English ---
                res_nat = call_llm(prompt_natural(glossary), chunk).split('\n')
                
                # --- PASS 2: Literal English ---
                res_lit = call_llm(prompt_literal(), chunk).split('\n')
                
                # --- PASS 3: Pinyin ---
                res_py = call_llm(prompt_pinyin(), chunk).split('\n')
                
                # --- PASS 4: JSON Extraction ---
                res_json = call_llm(prompt_json(glossary), chunk)

            # Update Glossary from Pass 4
            try:
                json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
                new_data = json.loads(json_str)
                glossary["characters"].update(new_data.get("characters", {}))
                glossary["places"].update(new_data.get("places", {}))
            except Exception as e:
                logging.warning(f"JSON Parse Error in Chunk {i+1}: {e} - AI Output: {res_json}")

            # Merge the lines from Passes 1, 2, and 3
            # We use zip to align the lines. If the AI hallucinates and returns different line counts, zip() stops at the shortest.
            cards_in_chunk = 0
            for cn, nat, lit, py in zip(chunk_lines, res_nat, res_lit, res_py):
                # Clean up any potential markdown bullets the AI added
                nat = nat.lstrip('- *').strip()
                lit = lit.lstrip('- *').strip()
                py = py.lstrip('- *').strip()

                full_translated_text += nat + "\n"

                # Add to Anki
                note = genanki.Note(model=my_model, fields=[cn, py, lit, nat], tags=[novel_name, f"Ch_{chapter.chapter_number}"])
                my_deck.add_note(note)
                
                # Add to EPUB HTML
                epub_chapter_html += f"""
                <div class="study-block">
                    <p class="cn">{cn}</p>
                    <p class="py">{py}</p>
                    <p class="lit">"{lit}"</p>
                    <p class="en">{nat}</p>
                </div>
                """
                cards_in_chunk += 1
                cards_added_in_chapter += 1

            console.print(f"[dim]Chunk {i+1}: Combined {cards_in_chunk} lines successfully.[/dim]")

        console.print(f"[green]✓ Chapter {chapter.file_name} complete. Total cards: {cards_added_in_chapter}[/green]")

        # Save Translated Text File
        (trans_dir / chapter.file_name).write_text(full_translated_text, encoding='utf-8')
        
        # Add Chapter to EPUB
        epub_ch = epub.EpubHtml(title=chapter.file_name, file_name=f"{chapter.file_name}.xhtml", lang='en')
        epub_ch.content = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_chapter_html}</body></html>"
        epub_ch.add_item(epub_css)
        book.add_item(epub_ch)
        book_chapters.append(epub_ch)

    # Save Glossary
    glossary_file.write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')

    # Export Anki
    anki_path = novel_dir / f"{novel_name}.apkg"
    genanki.Package(my_deck).write_to_file(str(anki_path))
    
    # Export EPUB
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
