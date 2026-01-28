import os
import json
import time
import gc
import threading
import torch
import ollama
import genanki
import soundfile as sf
import transformers
import numpy as np
import re
from pathlib import Path

# Local Imports
from config import LLM_MODEL, TTS_MODEL, SPEAKER_VOICE, ANKI_MODEL, get_deterministic_id
from utils import Chapter, extract_chapter_number, chunk_text_into_numbered_lines, get_relevant_glossary, call_llm, parse_numbered_output, clean_for_tts, sanitize_filename, generate_pinyin
from prompts import prompt_json, prompt_natural, prompt_literal, prompt_emotion
from exporters import build_final_epub
from qwen_tts import Qwen3TTSModel

# --- HELPER: DIRECTORY SETUP ---
def setup_directories(novel_dir):
    paths = {
        "raw": novel_dir / "01_Raw_Text",
        "trans": novel_dir / "02_Translated",
        "epub": novel_dir / "03_EPUB_Chapters",
        "anki": novel_dir / "04_Anki_Chapters",
        "media": novel_dir / "media",
        "cache": novel_dir / ".cache",
        "glossary": novel_dir / "glossary.json",
        "metadata": novel_dir / "metadata.json"
    }
    for p in paths.values():
        if p.suffix == "": # If it's a folder, create it
            p.mkdir(exist_ok=True)
    return paths

# --- STAGE 1: TEXT GENERATION ---
def run_text_stage(chapter, paths, glossary, stop_event, redo_pinyin):
    print("\n--- STAGE 1: TEXT GENERATION ---")
    
    consolidated_json = paths["trans"] / chapter.file_name.replace('.txt', '.json')
    chapter_cache_dir = paths["cache"] / f"ch_{chapter.chapter_number:04d}"
    chapter_cache_dir.mkdir(exist_ok=True)
    chapter_lines = []

    # 1. Redo Pinyin Mode (Fast Path)
    if redo_pinyin and consolidated_json.exists():
        print(f"    [Pinyin] Re-generating Pinyin for {chapter.file_name}...")
        data = json.loads(consolidated_json.read_text(encoding='utf-8'))
        for line in data:
            if "cn" in line: line["py"] = generate_pinyin(line["cn"])
        consolidated_json.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding='utf-8')
        return data # Return immediately

    # 2. Load Existing Full Translation
    if consolidated_json.exists():
        print(f"    - Full chapter loaded from visible directory: {consolidated_json.name}")
        return json.loads(consolidated_json.read_text(encoding='utf-8'))

    # 3. Process Chunks (The Heavy Lifting)
    chunks = chunk_text_into_numbered_lines(chapter.content)
    total_lines = sum(len(c) for c in chunks)

    for i, chunk_dict in enumerate(chunks):
        if stop_event.is_set(): return []
        
        chunk_cache_file = chapter_cache_dir / f"chunk_{i:04d}.json"
        if chunk_cache_file.exists():
            print(f"    - Chunk {i+1}/{len(chunks)}: Loaded from hidden cache.")
            chapter_lines.extend(json.loads(chunk_cache_file.read_text(encoding='utf-8')))
            continue

        print(f"    - Chunk {i+1}/{len(chunks)} ({len(chunk_dict)} lines): Sending to LLM...")
        numbered_input = "\n".join([f"{idx}. {text}" for idx, text in chunk_dict.items()])

        # Dynamic Glossary Update
        try:
            res_json = call_llm(prompt_json(), numbered_input)
            json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
            new_entities = json.loads(json_str)
            glossary_changed = False
            for cat in ["characters", "places"]:
                for name, data in new_entities.get(cat, {}).items():
                    if name not in glossary[cat]:
                        glossary[cat][name] = data
                        glossary_changed = True
            if glossary_changed:
                paths["glossary"].write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')
        except Exception: pass

        # LLM Translations
        chunk_glossary = get_relevant_glossary(numbered_input, glossary)
        nat = parse_numbered_output(call_llm(prompt_natural(chunk_glossary), numbered_input), len(chunk_dict))
        lit = parse_numbered_output(call_llm(prompt_literal(chunk_glossary), numbered_input), len(chunk_dict))
        emo = parse_numbered_output(call_llm(prompt_emotion(), numbered_input), len(chunk_dict))
        
        current_chunk_lines = []
        for idx, text in chunk_dict.items():
            current_chunk_lines.append({
                "cn": text,
                "py": generate_pinyin(text), # Local Pinyin
                "nat": nat.get(idx, ""),
                "lit": lit.get(idx, ""),
                "emo": emo.get(idx, "Calm narrative")
            })
        
        chunk_cache_file.write_text(json.dumps(current_chunk_lines, ensure_ascii=False), encoding='utf-8')
        chapter_lines.extend(current_chunk_lines)

    # 4. Cleanup and Save
    if not stop_event.is_set() and len(chapter_lines) == total_lines:
        print(f"\n    - Translation complete. Saving master JSON to: 02_Translated/{consolidated_json.name}")
        consolidated_json.write_text(json.dumps(chapter_lines, ensure_ascii=False, indent=4), encoding='utf-8')
        for chunk_file in chapter_cache_dir.glob("chunk_*.json"): chunk_file.unlink()

    return chapter_lines

# --- STAGE 2: AUDIO & DECK GENERATION ---
def run_audio_stage(chapter, chapter_lines, novel_name, paths, stop_event, redo_pinyin):
    print("\n--- STAGE 2: AUDIO & COMPILATION ---")
    transformers.logging.set_verbosity_error()

    # VRAM Cleanup
    if not redo_pinyin:
        print("\n[SYSTEM] Unloading LLM to free VRAM for Audio...")
        ollama.generate(model=LLM_MODEL, prompt="", keep_alive=0)
        time.sleep(1)

    # Setup Anki Deck
    safe_deck_title = sanitize_filename(novel_name).replace("_", " ")
    chapter_deck_id = get_deterministic_id(f"{novel_name}_Ch_{chapter.chapter_number}")
    chapter_deck = genanki.Deck(chapter_deck_id, f'{safe_deck_title}::Ch {chapter.chapter_number:03d}')
    
    chapter_media_dir = paths["media"] / f"ch_{chapter.chapter_number:04d}"
    chapter_media_dir.mkdir(exist_ok=True)
    
    chapter_media_files = []
    full_text_en = ""
    epub_body = f"<h1>{chapter_lines[0]['nat'] if chapter_lines else chapter.file_name}</h1>\n"
    
    tts_model = None
    audio_count = 0

    for line_idx, line in enumerate(chapter_lines):
        if stop_event.is_set(): break
        
        audio_filename = f"ch{chapter.chapter_number:02d}_L{line_idx:04d}.opus"
        audio_path = chapter_media_dir / audio_filename
        
        # Audio Logic
        skip_audio = audio_path.exists() and audio_path.stat().st_size > 1024
        if not skip_audio: audio_path.unlink(missing_ok=True)

        if not skip_audio and not redo_pinyin:
            # Model Management
            if tts_model and audio_count > 0 and audio_count % 30 == 0:
                print(f"[SYSTEM] Auto-reloading TTS model...")
                del tts_model
                gc.collect()
                torch.cuda.empty_cache()
                tts_model = None
            
            if not tts_model:
                print(f"[SYSTEM] Loading Qwen3-TTS ({TTS_MODEL})...")
                tts_model = Qwen3TTSModel.from_pretrained(TTS_MODEL, device_map="cuda:0", dtype=torch.float16, attn_implementation="sdpa")

            # Generation
            raw_text = clean_for_tts(line["cn"]) or "标题"
            emo_tag = re.sub(r'[^a-zA-Z0-9\s]', '', line.get("emo", "Calm narrative").strip())
            if len(emo_tag.split()) > 6: emo_tag = "Calm narrative"
            
            print(f"    [Audio] L{line_idx+1}/{len(chapter_lines)}: [{emo_tag}] {raw_text[:40]}...")
            
            with torch.no_grad():
                wavs, sr = tts_model.generate_custom_voice(text=raw_text, language="Chinese", speaker=SPEAKER_VOICE, instruct=emo_tag)
            
            # Save
            if torch.is_tensor(wavs[0]):
                audio_t = wavs[0]
                if audio_t.numel() == 0 or torch.isnan(audio_t).any() or torch.isinf(audio_t).any():
                    audio_data = np.zeros(int(sr * 1.0), dtype=np.float32)
                else:
                    audio_data = audio_t.detach().cpu().to(torch.float32).contiguous().numpy().copy()
            else:
                audio_data = np.asarray(wavs[0], dtype=np.float32).copy()

            sf.write(str(audio_path), audio_data, sr, format='OGG', subtype='OPUS')
            del wavs, audio_data
            gc.collect()
            torch.cuda.empty_cache()
            audio_count += 1

        # Collect Results
        chapter_media_files.append(str(audio_path))
        
        # Create Anki Note
        guid = genanki.guid_for(f"{novel_name}_Ch_{chapter.chapter_number:03d}_L{line_idx:04d}")
        note = genanki.Note(
            model=ANKI_MODEL, guid=guid, 
            fields=[line["cn"], line["py"], line["lit"], line["nat"], f"[sound:{audio_filename}]"], 
            tags=[novel_name, f"Ch_{chapter.chapter_number:03d}"]
        )
        chapter_deck.add_note(note)

        # Build HTML
        full_text_en += line["nat"] + "\n"
        epub_body += f"""
        <div class="study-block">
            <p class="cn">{line["cn"]}</p>
            <p class="py">{line["py"]}</p>
            <p class="lit">"{line["lit"]}"</p>
            <p class="en">{line["nat"]}</p>
            <audio controls preload="none"><source src="media/ch_{chapter.chapter_number:04d}/{audio_filename}" type="audio/ogg"></audio>
        </div>"""

    if tts_model: 
        del tts_model
        gc.collect()
        torch.cuda.empty_cache()

    return chapter_deck, chapter_media_files, full_text_en, epub_body

# --- STAGE 3: EXPORT ---
def run_export_stage(chapter, chapter_deck, media_files, full_text, epub_html, paths, novel_name, all_chapter_decks, global_media_list):
    print(f"    [Export] Saving files for {chapter.file_name}...")
    
    # 1. Update Master Lists
    all_chapter_decks.append(chapter_deck)
    for m in media_files:
        if m not in global_media_list: global_media_list.append(m)

    # 2. Export Single Chapter Anki
    ch_apkg_path = paths["anki"] / f"Ch_{chapter.chapter_number:03d}.apkg"
    ch_package = genanki.Package(chapter_deck)
    ch_package.media_files = media_files
    ch_package.write_to_file(str(ch_apkg_path))

    # 3. Save Text & XHTML
    (paths["trans"] / chapter.file_name).write_text(full_text, encoding='utf-8')
    xhtml_path = paths["epub"] / chapter.file_name.replace('.txt', '.xhtml')
    xhtml_path.write_text(f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_html}</body></html>", encoding='utf-8')

    # 4. Update Master Book Files
    meta = json.loads(paths["metadata"].read_text(encoding='utf-8')) if paths["metadata"].exists() else {}
    safe_title = sanitize_filename(meta.get("title", novel_name))
    
    build_final_epub(safe_title, paths["raw"].parent, meta)
    
    anki_package = genanki.Package(all_chapter_decks)
    anki_package.media_files = global_media_list
    anki_package.write_to_file(str(paths["raw"].parent / (safe_title + ".apkg")))
    
    print(f"✓ {chapter.file_name} successfully finished and exported.")

# --- MAIN CONTROLLER ---
def process_novel(novel_dir, start_chapter: int, stop_event: threading.Event, redo_pinyin: bool = False):
    paths = setup_directories(novel_dir)
    glossary = json.loads(paths["glossary"].read_text()) if paths["glossary"].exists() else {"characters": {}, "places": {}}
    
    all_chapter_decks = []
    global_media_list = []

    # Load Chapters
    all_files = sorted(paths["raw"].glob("*.txt"))
    chapters = []
    for f in all_files:
        ch_num = extract_chapter_number(f.name)
        if ch_num is not None and ch_num >= start_chapter:
            chapters.append(Chapter(novel_dir.name, f.name, f.read_text(encoding='utf-8'), ch_num))

    print(f"Loaded {len(chapters)} chapters for processing.")

    for chapter in chapters:
        if stop_event.is_set(): break
        print(f"\n{'='*50}\n>>> PROCESSING: {chapter.file_name}\n{'='*50}")

        # Verification Check
        json_path = paths["trans"] / chapter.file_name.replace('.txt', '.json')
        apkg_path = paths["anki"] / f"Ch_{chapter.chapter_number:03d}.apkg"
        audio_count = len(list((paths["media"] / f"ch_{chapter.chapter_number:04d}").glob("*.opus")))
        # Quick logic: Roughly check lines vs audio files (if we have lines loaded)
        # For simplicity in Main Controller, we proceed to stages which handle skipping internally
        if json_path.exists() and apkg_path.exists() and not redo_pinyin:
             # Basic verification to avoid spamming "Loaded" if unnecessary
             pass 

        # --- EXECUTE PIPELINE ---
        
        # 1. Text Stage
        lines = run_text_stage(chapter, paths, glossary, stop_event, redo_pinyin)
        if not lines or stop_event.is_set(): continue

        # 2. Audio Stage
        deck, media, text_en, html = run_audio_stage(chapter, lines, novel_dir.name, paths, stop_event, redo_pinyin)
        if stop_event.is_set(): continue

        # 3. Export Stage
        run_export_stage(chapter, deck, media, text_en, html, paths, novel_dir.name, all_chapter_decks, global_media_list)

    print(f"\n[✓] PIPELINE COMPLETED SUCCESSFULLY.")
