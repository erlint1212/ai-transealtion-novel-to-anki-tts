import ollama
import genanki
import random
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# --- CONFIGURATION ---
MODEL_NAME = "qwen2.5:14b-instruct-q5_K_M"
NOVELS_ROOT_DIR = "./Novels"
OUTPUT_DECK = "Novel_Translations.apkg"

# Anki IDs
DECK_ID = random.randrange(1 << 30, 1 << 31)
MODEL_ID = random.randrange(1 << 30, 1 << 31)

SYSTEM_PROMPT = """You are an expert Chinese to English translator.
1. Translate the Chinese text to English.
2. Convert all measurements to metric and temperatures to Celsius.
3. For every sentence or paragraph, output exactly one bullet point formatted strictly as:
[Original Chinese] * [Natural English] * [Literal English] * [Pinyin]
"""

# --- DATACLASSES & FILE LOADING ---
@dataclass
class Chapter:
    novel_name: str
    file_name: str
    content: str
    chapter_number: Optional[int] = None

def extract_chapter_number(file_name: str) -> Optional[int]:
    try:
        # Splits 'ch_0002.txt' -> 2
        return int(file_name.split('.')[0].split('_')[1])
    except (IndexError, ValueError):
        return None

def load_novel_chapters(base_dir: str) -> List[Chapter]:
    """Crawls the directory structure and loads all .txt files."""
    base_path = Path(base_dir)
    chapters = []

    if not base_path.exists():
        console.print(f"[red]Error: Base directory '{base_dir}' does not exist.[/red]")
        return []

    for novel_dir in base_path.iterdir():
        if novel_dir.is_dir():
            raw_text_dir = novel_dir / "01_Raw_Text"
            if raw_text_dir.exists() and raw_text_dir.is_dir():
                for txt_file in raw_text_dir.glob("*.txt"):
                    try:
                        with open(txt_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                        chapters.append(Chapter(
                            novel_name=novel_dir.name,
                            file_name=txt_file.name,
                            content=content,
                            chapter_number=extract_chapter_number(txt_file.name)
                        ))
                    except Exception as e:
                        console.print(f"[yellow]Failed to read {txt_file}: {e}[/yellow]")

    chapters.sort(key=lambda x: (x.novel_name, x.chapter_number if x.chapter_number is not None else float('inf')))
    return chapters

# --- ANKI SETUP ---
my_model = genanki.Model(
    MODEL_ID,
    'Chinese Translation Model',
    fields=[
        {'name': 'Chinese'},
        {'name': 'Pinyin'},
        {'name': 'LiteralEnglish'},
        {'name': 'NaturalEnglish'},
    ],
    templates=[
        {
            'name': 'Card 1',
            'qfmt': '<h1 style="text-align:center; font-size:40px;">{{Chinese}}</h1>',
            'afmt': '{{FrontSide}}<hr id="answer"><div style="text-align:center; font-size:24px; color:#555;">{{Pinyin}}</div><br><div style="text-align:center; font-size:20px;"><i>"{{LiteralEnglish}}"</i></div><br><div style="text-align:center; font-size:28px; font-weight:bold;">{{NaturalEnglish}}</div>',
        },
    ],
    css='.card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }'
)

my_deck = genanki.Deck(DECK_ID, 'Local LLM: Novel Translations')

# --- LLM & PARSING ---
def generate_translations(text, chapter_info):
    """Sends text to local Ollama."""
    with Progress(SpinnerColumn(), TextColumn(f"[bold blue]Translating {chapter_info}..."), transient=True) as progress:
        progress.add_task("translating", total=None)
        response = ollama.chat(model=MODEL_NAME, messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': f"Text to translate:\n{text}"}
        ])
    return response['message']['content']

def parse_and_add_notes(llm_output, novel_name, chapter_num):
    """Parses output and adds tags based on the novel and chapter."""
    added_count = 0
    lines = llm_output.strip().split('\n')
    
    # Create tags for Anki (e.g., "My_Novel", "Chapter_2")
    tags = [novel_name.replace(" ", "_")]
    if chapter_num is not None:
        tags.append(f"Chapter_{chapter_num}")
    
    for line in lines:
        if line.startswith(('-', '*')):
            line = line.lstrip('- *')
            parts = [p.strip() for p in line.split('*')]
            
            if len(parts) == 4:
                chinese, natural, literal, pinyin = parts
                note = genanki.Note(
                    model=my_model,
                    fields=[chinese, pinyin, literal, natural],
                    tags=tags # Tag the card with Novel and Chapter
                )
                my_deck.add_note(note)
                added_count += 1
            else:
                pass # Silently skip malformed lines
                
    return added_count

def chunk_text(text, max_chars=1500):
    """Splits long chapters by newlines to preserve sentence/paragraph context."""
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_length = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue # Skip empty lines

        # If adding this line exceeds the limit, save the current chunk and start a new one
        if current_length + len(line) > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_length = 0

        current_chunk.append(line)
        current_length += len(line)

    # Don't forget the last chunk
    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks

# --- MAIN EXECUTION ---
def main():
    console.print("[bold green]Loading novels from directory...[/bold green]")
    chapters = load_novel_chapters(NOVELS_ROOT_DIR)
    
    if not chapters:
        console.print("[red]No chapters found. Please check your /Novels/ directory.[/red]")
        return

    total_cards = 0

    for chapter in chapters:
        chapter_label = f"{chapter.novel_name} - {chapter.file_name}"
        console.print(f"\n[bold]Processing {chapter_label}[/bold]")
        
        # Split chapter into chunks
        chunks = chunk_text(chapter.content)
        
        for i, chunk in enumerate(chunks):
            chunk_label = f"Part {i+1}/{len(chunks)}"
            llm_output = generate_translations(chunk, f"{chapter_label} ({chunk_label})")
            count = parse_and_add_notes(llm_output, chapter.novel_name, chapter.chapter_number)
            total_cards += count
            console.print(f"[green]✓ {chunk_label}: Added {count} cards.[/green]")

    # Export
    console.print("\n[bold]Finalizing Anki Deck...[/bold]")
    genanki.Package(my_deck).write_to_file(OUTPUT_DECK)
    console.print(f"[bold green]Success![/bold green] Generated {total_cards} total cards and saved to {OUTPUT_DECK}")

if __name__ == "__main__":
    main()
