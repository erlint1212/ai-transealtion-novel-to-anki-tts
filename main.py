import os
import json
import time
import gc
import torch
import ollama
import genanki
import soundfile as sf
import threading

# Local Imports
from config import LLM_MODEL, TTS_MODEL, SPEAKER_VOICE, NOVELS_ROOT_DIR, DECK_ID, ANKI_MODEL
from utils import Chapter, extract_chapter_number, chunk_text_into_numbered_lines, get_relevant_glossary, call_llm, parse_numbered_output, clean_for_tts
from prompts import prompt_json, prompt_natural, prompt_literal, prompt_pinyin
from exporters import build_final_epub

def process_novel(novel_dir, start_chapter: int, stop_event: threading.Event):
    novel_name = novel_dir.name
    raw_dir = novel_dir / "01_Raw_Text"
    trans_dir = novel_dir / "02_Translated"
    epub_dir = novel_dir / "03_EPUB_Chapters"
    media_dir = novel_dir / "media"
    
    trans_dir.mkdir(exist_ok=True)
    epub_dir.mkdir(exist_ok=True)
    media_dir.mkdir(exist_ok=True)
    
    glossary_file = novel_dir / "glossary.json"
    glossary = json.loads(glossary_file.read_text()) if glossary_file.exists() else {"characters": {}, "places": {}}

    my_deck = genanki.Deck(DECK_ID, f'{novel_name} Vocab & Audio')
    media_files_for_anki = []
    
    all_raw_files = sorted(raw_dir.glob("*.txt"))
    chapters = []
    for f in all_raw_files:
        ch_num = extract_chapter_number(f.name)
        if ch_num is not None and ch_num >= start_chapter:
            chapters.append(Chapter(novel_name, f.name, f.read_text(encoding='utf-8'), ch_num))

    print(f"Loaded {len(chapters)} chapters for processing.")

    # --- STAGE 1: LLM TRANSLATION ---
    all_translated_data = []
    print(f"\n{'='*20} STAGE 1: LLM TRANSLATION {'='*20}")
    
    for chapter in chapters:
        if stop_event.is_set(): return

        print(f"\n>>> Processing {chapter.file_name}...")
        chunks = chunk_text_into_numbered_lines(chapter.content)
        chapter_data = {"chapter": chapter, "lines": []}
        
        for i, chunk_dict in enumerate(chunks):
            if stop_event.is_set(): return
            
            chunk_size = len(chunk_dict)
            print(f"    - Chunk {i+1}/{len(chunks)} ({chunk_size} lines): Sending to Qwen2.5-14b...")
            
            numbered_input = "\n".join([f"{idx}. {text}" for idx, text in chunk_dict.items()])
            
            t0 = time.time()
            res_json = call_llm(prompt_json(), numbered_input)
            try:
                json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
                new_entities = json.loads(json_str)
                for c_name, c_data in new_entities.get("characters", {}).items():
                    if c_name not in glossary["characters"]:
                        print(f"      [Glossary] Found new character: {c_name} -> {c_data['english_name']}")
                        glossary["characters"][c_name] = c_data
                for p_name, p_data in new_entities.get("places", {}).items():
                    if p_name not in glossary["places"]:
                        print(f"      [Glossary] Found new place: {p_name} -> {p_data['english_name']}")
                        glossary["places"][p_name] = p_data
            except Exception: pass

            chunk_glossary = get_relevant_glossary(numbered_input, glossary)
            
            print(f"      [LLM] Translating (Natural)...")
            nat_dict = parse_numbered_output(call_llm(prompt_natural(chunk_glossary), numbered_input), chunk_size)
            print(f"      [LLM] Translating (Literal)...")
            lit_dict = parse_numbered_output(call_llm(prompt_literal(chunk_glossary), numbered_input), chunk_size)
            print(f"      [LLM] Generating Pinyin...")
            py_dict = parse_numbered_output(call_llm(prompt_pinyin(chunk_glossary), numbered_input), chunk_size)

            for idx in range(1, chunk_size + 1):
                chapter_data["lines"].append({
                    "cn": chunk_dict[idx], "nat": nat_dict[idx], "lit": lit_dict[idx], "py": py_dict[idx]
                })
            print(f"    ✓ Chunk {i+1} completed in {time.time() - t0:.1f}s.")

        all_translated_data.append(chapter_data)

    if stop_event.is_set(): return

    # --- VRAM SAFETY BRIDGE ---
    print("\n[SYSTEM] Unloading LLM from GPU to free memory for TTS...")
    ollama.generate(model=LLM_MODEL, prompt="", keep_alive=0)
    time.sleep(2)

    # --- STAGE 2: QWEN3-TTS AUDIO GENERATION ---
    print(f"\n{'='*20} STAGE 2: TTS AUDIO GENERATION {'='*20}")
    print(f"[SYSTEM] Loading Qwen3-TTS ({TTS_MODEL}) into VRAM...")
    
    from qwen_tts import Qwen3TTSModel
    tts_model = Qwen3TTSModel.from_pretrained(TTS_MODEL, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="flash_attention_2")

    for chapter_data in all_translated_data:
        if stop_event.is_set(): break

        chapter = chapter_data["chapter"]
        lines = chapter_data["lines"]
        chapter_title_en = lines[0]["nat"] if lines else chapter.file_name
        
        chapter_media_dir = media_dir / f"ch_{chapter.chapter_number:04d}"
        chapter_media_dir.mkdir(exist_ok=True)
        
        full_translated_text = ""
        epub_body_html = f"<h1>{chapter_title_en}</h1>\n"
        
        print(f"\n>>> Generating Audio for {chapter.file_name} ({len(lines)} lines)...")
        
        for line_idx, line in enumerate(lines):
            if stop_event.is_set(): break

            tts_text = clean_for_tts(line["cn"]) or "标题"
            audio_filename = f"ch{chapter.chapter_number:02d}_L{line_idx:04d}.opus"
            audio_filepath = chapter_media_dir / audio_filename
            
            # Print text to show what is being generated
            print(f"    [Audio] Generating ({line_idx+1}/{len(lines)}): {tts_text[:40]}...")

            wavs, sr = tts_model.generate_custom_voice(text=tts_text, language="Chinese", speaker=SPEAKER_VOICE)
            sf.write(str(audio_filepath), wavs[0], sr, format='OGG', subtype='OPUS')
            media_files_for_anki.append(str(audio_filepath))

            note = genanki.Note(
                model=ANKI_MODEL, 
                fields=[line["cn"], line["py"], line["lit"], line["nat"], f"[sound:{audio_filename}]"], 
                tags=[novel_name, f"Ch_{chapter.chapter_number}"]
            )
            my_deck.add_note(note)

            full_translated_text += line["nat"] + "\n"
            epub_body_html += f"""
            <div class="study-block">
                <p class="cn">{line["cn"]}</p>
                <p class="py">{line["py"]}</p>
                <p class="lit">"{line["lit"]}"</p>
                <p class="en">{line["nat"]}</p>
                <audio controls preload="none">
                    <source src="media/ch_{chapter.chapter_number:04d}/{audio_filename}" type="audio/ogg">
                </audio>
            </div>
            """

        (trans_dir / chapter.file_name).write_text(full_translated_text, encoding='utf-8')
        epub_html_full = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_body_html}</body></html>"
        xhtml_filename = chapter.file_name.replace('.txt', '.xhtml')
        (epub_dir / xhtml_filename).write_text(epub_html_full, encoding='utf-8')
        print(f"✓ {chapter.file_name} successfully saved to disk.")

    del tts_model
    gc.collect()
    torch.cuda.empty_cache()

    if stop_event.is_set(): return

    # --- STAGE 3: COMPILATION ---
    print(f"\n{'='*20} STAGE 3: COMPILATION {'='*20}")
    print("[SYSTEM] Compiling final .apkg and .epub files...")
    
    # Save the updated glossary
    glossary_file.write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')
    
    # --- LOAD NOVEL METADATA ---
    metadata_file = novel_dir / "metadata.json"
    novel_metadata = {}
    if metadata_file.exists():
        try:
            novel_metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
            print("    [Metadata] Successfully loaded metadata.json (Cover, Author, Title).")
        except json.JSONDecodeError:
            print("    [Warning] metadata.json is malformed. Using default values.")

    # Build EPUB with Metadata
    build_final_epub(novel_name, novel_dir, novel_metadata)
    
    # Pack Anki
    anki_package = genanki.Package(my_deck)
    anki_package.media_files = media_files_for_anki
    deck_filename = novel_metadata.get("title", novel_name) + ".apkg"
    anki_package.write_to_file(str(novel_dir / deck_filename))
    
    print(f"\n[✓] DONE! Successfully generated {deck_filename} and the EPUB.")
