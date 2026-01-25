import os
import json
import time
import gc
import torch
import ollama
import genanki
import soundfile as sf
from rich.progress import Progress, SpinnerColumn, TextColumn

# Local Imports
from config import console, LLM_MODEL, TTS_MODEL, SPEAKER_VOICE, NOVELS_ROOT_DIR, DECK_ID, ANKI_MODEL
from utils import Chapter, extract_chapter_number, chunk_text_into_numbered_lines, get_relevant_glossary, call_llm, parse_numbered_output, clean_for_tts
from prompts import prompt_json, prompt_natural, prompt_literal, prompt_pinyin
from exporters import build_final_epub

def process_novel(novel_dir):
    novel_name = novel_dir.name
    raw_dir = novel_dir / "01_Raw_Text"
    trans_dir = novel_dir / "02_Translated"
    epub_dir = novel_dir / "03_EPUB_Chapters" # New modular directory
    media_dir = novel_dir / "media"
    
    trans_dir.mkdir(exist_ok=True)
    epub_dir.mkdir(exist_ok=True)
    media_dir.mkdir(exist_ok=True)
    
    glossary_file = novel_dir / "glossary.json"
    glossary = json.loads(glossary_file.read_text()) if glossary_file.exists() else {"characters": {}, "places": {}}

    my_deck = genanki.Deck(DECK_ID, f'{novel_name} Vocab & Audio')
    media_files_for_anki = []
    
    chapters = [Chapter(novel_name, f.name, f.read_text(encoding='utf-8'), extract_chapter_number(f.name)) for f in sorted(raw_dir.glob("*.txt"))]

    # --- STAGE 1: LLM TRANSLATION ---
    all_translated_data = []
    console.print(f"\n[bold magenta]=== STAGE 1: LLM TRANSLATION ===[/bold magenta]")
    
    for chapter in chapters:
        console.print(f"[bold]Translating Chapter: {chapter.file_name}[/bold]")
        chunks = chunk_text_into_numbered_lines(chapter.content)
        chapter_data = {"chapter": chapter, "lines": []}
        
        for chunk_dict in chunks:
            chunk_size = len(chunk_dict)
            numbered_input = "\n".join([f"{idx}. {text}" for idx, text in chunk_dict.items()])
            
            with Progress(SpinnerColumn(), TextColumn(f"[blue]Processing..."), transient=True) as progress:
                progress.add_task("translating", total=None)
                
                # JSON Extraction
                res_json = call_llm(prompt_json(), numbered_input)
                try:
                    json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
                    new_entities = json.loads(json_str)
                    for c_name, c_data in new_entities.get("characters", {}).items():
                        if c_name not in glossary["characters"]: glossary["characters"][c_name] = c_data
                    for p_name, p_data in new_entities.get("places", {}).items():
                        if p_name not in glossary["places"]: glossary["places"][p_name] = p_data
                except Exception: pass

                # Micro-Glossary + Translations
                chunk_glossary = get_relevant_glossary(numbered_input, glossary)
                nat_dict = parse_numbered_output(call_llm(prompt_natural(chunk_glossary), numbered_input), chunk_size)
                lit_dict = parse_numbered_output(call_llm(prompt_literal(chunk_glossary), numbered_input), chunk_size)
                py_dict = parse_numbered_output(call_llm(prompt_pinyin(chunk_glossary), numbered_input), chunk_size)

            for idx in range(1, chunk_size + 1):
                chapter_data["lines"].append({
                    "cn": chunk_dict[idx], "nat": nat_dict[idx], "lit": lit_dict[idx], "py": py_dict[idx]
                })

        all_translated_data.append(chapter_data)

    # --- VRAM SAFETY BRIDGE ---
    console.print("[yellow]Unloading LLM from GPU to free memory for TTS...[/yellow]")
    ollama.generate(model=LLM_MODEL, prompt="", keep_alive=0)
    time.sleep(2)

    # --- STAGE 2: QWEN3-TTS AUDIO GENERATION ---
    console.print(f"\n[bold magenta]=== STAGE 2: AUDIO GENERATION ===[/bold magenta]")
    
    from qwen_tts import Qwen3TTSModel
    tts_model = Qwen3TTSModel.from_pretrained(TTS_MODEL, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="flash_attention_2")

    for chapter_data in all_translated_data:
        chapter = chapter_data["chapter"]
        lines = chapter_data["lines"]
        chapter_title_en = lines[0]["nat"] if lines else chapter.file_name
        
        full_translated_text = ""
        epub_body_html = f"<h1>{chapter_title_en}</h1>\n"
        
        with Progress(SpinnerColumn(), TextColumn(f"[cyan]Generating audio & HTML for {chapter.file_name}..."), transient=True) as progress:
            progress.add_task("tts", total=None)
            for line_idx, line in enumerate(lines):
                
                # 1. Generate Audio
                tts_text = clean_for_tts(line["cn"]) or "标题"
                audio_filename = f"ch{chapter.chapter_number:02d}_L{line_idx:04d}.wav"
                audio_filepath = media_dir / audio_filename
                
                wavs, sr = tts_model.generate_custom_voice(text=tts_text, language="Chinese", speaker=SPEAKER_VOICE)
                sf.write(str(audio_filepath), wavs[0], sr)
                media_files_for_anki.append(str(audio_filepath))

                # 2. Add to Anki
                note = genanki.Note(
                    model=ANKI_MODEL, 
                    fields=[line["cn"], line["py"], line["lit"], line["nat"], f"[sound:{audio_filename}]"], 
                    tags=[novel_name, f"Ch_{chapter.chapter_number}"]
                )
                my_deck.add_note(note)

                # 3. Add to Text/EPUB HTML
                full_translated_text += line["nat"] + "\n"
                epub_body_html += f"""
                <div class="study-block">
                    <p class="cn">{line["cn"]}</p>
                    <p class="py">{line["py"]}</p>
                    <p class="lit">"{line["lit"]}"</p>
                    <p class="en">{line["nat"]}</p>
                    <audio controls preload="none">
                        <source src="media/{audio_filename}" type="audio/wav">
                    </audio>
                </div>
                """

        # Save Text and modular .xhtml files to disk immediately
        (trans_dir / chapter.file_name).write_text(full_translated_text, encoding='utf-8')
        
        epub_html_full = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_body_html}</body></html>"
        xhtml_filename = chapter.file_name.replace('.txt', '.xhtml')
        (epub_dir / xhtml_filename).write_text(epub_html_full, encoding='utf-8')

    # UNLOAD TTS
    del tts_model
    gc.collect()
    torch.cuda.empty_cache()

    # --- STAGE 3: COMPILATION ---
    console.print(f"\n[bold magenta]=== STAGE 3: COMPILING FINAL EPUB ===[/bold magenta]")
    glossary_file.write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')
    
    # Pack EPUB using Exporters
    build_final_epub(novel_name, novel_dir)
    
    # Pack Anki
    anki_package = genanki.Package(my_deck)
    anki_package.media_files = media_files_for_anki
    anki_package.write_to_file(str(novel_dir / f"{novel_name}.apkg"))
    
    console.print(f"[bold green]✓ Done! Created Audio .apkg, .epub, and updated glossary in {novel_dir}[/bold green]")

if __name__ == "__main__":
    if not NOVELS_ROOT_DIR.exists(): exit()
    for novel_dir in NOVELS_ROOT_DIR.iterdir():
        if novel_dir.is_dir() and (novel_dir / "01_Raw_Text").exists():
            process_novel(novel_dir)
