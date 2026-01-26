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
from config import LLM_MODEL, TTS_MODEL, SPEAKER_VOICE, NOVELS_ROOT_DIR, ANKI_MODEL, get_deterministic_id
from utils import Chapter, extract_chapter_number, chunk_text_into_numbered_lines, get_relevant_glossary, call_llm, parse_numbered_output, clean_for_tts, sanitize_filename
from prompts import prompt_json, prompt_natural, prompt_literal, prompt_pinyin, prompt_emotion
from exporters import build_final_epub

from qwen_tts import Qwen3TTSModel
import transformers # NEW: needed to silence warnings
import numpy as np 
import re         

def process_novel(novel_dir, start_chapter: int, stop_event: threading.Event):
    novel_name = novel_dir.name
    raw_dir = novel_dir / "01_Raw_Text"
    trans_dir = novel_dir / "02_Translated"
    epub_dir = novel_dir / "03_EPUB_Chapters"
    anki_ch_dir = novel_dir / "04_Anki_Chapters"
    media_dir = novel_dir / "media"
    cache_dir = novel_dir / ".cache" 
    
    trans_dir.mkdir(exist_ok=True)
    epub_dir.mkdir(exist_ok=True)
    anki_ch_dir.mkdir(exist_ok=True)
    media_dir.mkdir(exist_ok=True)
    cache_dir.mkdir(exist_ok=True)
    
    glossary_file = novel_dir / "glossary.json"
    glossary = json.loads(glossary_file.read_text()) if glossary_file.exists() else {"characters": {}, "places": {}}

    #deck_id = get_deterministic_id(novel_name)
    #my_deck = genanki.Deck(deck_id, f'{novel_name} Vocab & Audio')
    all_chapter_decks = []
    
    media_files_for_anki = []
    
    all_raw_files = sorted(raw_dir.glob("*.txt"))
    chapters = []
    for f in all_raw_files:
        ch_num = extract_chapter_number(f.name)
        if ch_num is not None and ch_num >= start_chapter:
            chapters.append(Chapter(novel_name, f.name, f.read_text(encoding='utf-8'), ch_num))

    print(f"Loaded {len(chapters)} chapters for processing.")

    for chapter in chapters:
        if stop_event.is_set(): return

        # --- 1. STRICT VERIFICATION CHECK ---
        chunks = chunk_text_into_numbered_lines(chapter.content)
        total_chunks = len(chunks)
        total_lines = sum(len(c) for c in chunks)
        
        xhtml_path = epub_dir / chapter.file_name.replace('.txt', '.xhtml')
        ch_apkg_path = anki_ch_dir / f"Ch_{chapter.chapter_number:03d}.apkg"
        chapter_media_dir = media_dir / f"ch_{chapter.chapter_number:04d}"
        chapter_cache_dir = cache_dir / f"ch_{chapter.chapter_number:04d}"

        # --- NEW: Define the visible output path for the JSON data ---
        consolidated_json = trans_dir / chapter.file_name.replace('.txt', '.json')

        existing_audio = len(list(chapter_media_dir.glob("*.opus"))) if chapter_media_dir.exists() else 0

        # Verification Logic (Now checks for the visible JSON file instead of chunks)
        is_complete = (
            xhtml_path.exists() and 
            ch_apkg_path.exists() and 
            consolidated_json.exists() and  # <--- NEW
            existing_audio == total_lines
        )

        if is_complete:
            print(f">>> SKIPPING {chapter.file_name} (Verified 100% Complete).")
            # Register audio for the master compilation
            for audio_file in chapter_media_dir.glob("*.opus"):
                if str(audio_file) not in media_files_for_anki:
                    media_files_for_anki.append(str(audio_file))
            continue
            
        print(f"\n{'='*50}\n>>> PROCESSING/RESTORING: {chapter.file_name}\n{'='*50}")
        
        # --- STAGE 1: TEXT GENERATION (LLM) ---
        print("\n--- STAGE 1: TEXT GENERATION ---")
        chapter_lines = []
        chapter_cache_dir.mkdir(exist_ok=True)
        
        # 1. Check if the chapter is already fully translated in the visible folder
        if consolidated_json.exists():
            print(f"    - Full chapter loaded from visible directory: {consolidated_json.name}")
            chapter_lines = json.loads(consolidated_json.read_text(encoding='utf-8'))
        
        # 2. If not, process chunks in the hidden cache
        else:
            for i, chunk_dict in enumerate(chunks):
                if stop_event.is_set(): break
                chunk_size = len(chunk_dict)
                chunk_cache_file = chapter_cache_dir / f"chunk_{i:04d}.json"
                
                if chunk_cache_file.exists():
                    print(f"    - Chunk {i+1}/{len(chunks)}: Loaded from hidden cache.")
                    chapter_lines.extend(json.loads(chunk_cache_file.read_text(encoding='utf-8')))
                    continue

                print(f"    - Chunk {i+1}/{len(chunks)} ({chunk_size} lines): Sending to LLM...")
                numbered_input = "\n".join([f"{idx}. {text}" for idx, text in chunk_dict.items()])
                
                # Update Glossary (Optimized: Only writes to disk if changes occurred)
                try:
                    res_json = call_llm(prompt_json(), numbered_input)
                    # Extract JSON string safely
                    json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
                    new_entities = json.loads(json_str)
                    
                    glossary_changed = False # <--- Flag to track updates

                    for c_name, c_data in new_entities.get("characters", {}).items():
                        # STRICT CHECK: Only add if the key does NOT exist
                        if c_name not in glossary["characters"]: 
                            glossary["characters"][c_name] = c_data
                            glossary_changed = True
                            print(f"    [Glossary] Discovered new character: {c_name}")

                    for p_name, p_data in new_entities.get("places", {}).items():
                        # STRICT CHECK: Only add if the key does NOT exist
                        if p_name not in glossary["places"]: 
                            glossary["places"][p_name] = p_data
                            glossary_changed = True
                            print(f"    [Glossary] Discovered new place: {p_name}")

                    # Only write to disk if we actually added something
                    if glossary_changed:
                        glossary_file.write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')
                        
                except Exception as e: 
                    print(f"[WARNING] Glossary update failed: {e}") 
                    pass

                # Extract Translations
                chunk_glossary = get_relevant_glossary(numbered_input, glossary)
                nat_dict = {idx: "" for idx in range(1, chunk_size + 1)}
                lit_dict = {idx: "" for idx in range(1, chunk_size + 1)}
                py_dict  = {idx: "" for idx in range(1, chunk_size + 1)}
                emo_dict = {idx: "Calm narrative" for idx in range(1, chunk_size + 1)}

                try: nat_dict.update(parse_numbered_output(call_llm(prompt_natural(chunk_glossary), numbered_input), chunk_size))
                except: pass
                try: lit_dict.update(parse_numbered_output(call_llm(prompt_literal(chunk_glossary), numbered_input), chunk_size))
                except: pass
                try: py_dict.update(parse_numbered_output(call_llm(prompt_pinyin(chunk_glossary), numbered_input), chunk_size))
                except: pass
                try: emo_dict.update(parse_numbered_output(call_llm(prompt_emotion(), numbered_input), chunk_size))
                except: pass

                current_chunk_lines = []
                for idx in range(1, chunk_size + 1):
                    current_chunk_lines.append({
                        "cn": chunk_dict[idx], "nat": nat_dict[idx], "lit": lit_dict[idx], "py": py_dict[idx], "emo": emo_dict[idx]
                    })
                
                chunk_cache_file.write_text(json.dumps(current_chunk_lines, ensure_ascii=False), encoding='utf-8')
                chapter_lines.extend(current_chunk_lines)

            # 3. Consolidation & Cleanup (Moves it to the visible 02_Translated folder)
            if not stop_event.is_set() and len(chapter_lines) == total_lines:
                print(f"\n    - Translation complete. Saving master JSON to: 02_Translated/{consolidated_json.name}")
                consolidated_json.write_text(json.dumps(chapter_lines, ensure_ascii=False, indent=4), encoding='utf-8')
                
                print("    - Cleaning up hidden temporary chunks...")
                for chunk_file in chapter_cache_dir.glob("chunk_*.json"):
                    chunk_file.unlink()

        # --- VRAM BRIDGE: UNLOAD LLM ---
        print("\n[SYSTEM] Unloading LLM to free VRAM for Audio...")
        ollama.generate(model=LLM_MODEL, prompt="", keep_alive=0)
        time.sleep(1)

        # --- STAGE 2: AUDIO & FILE GENERATION ---
        print("\n--- STAGE 2: AUDIO & COMPILATION ---")

        transformers.logging.set_verbosity_error() 

        tts_model = None
        audio_count = 0 # NEW: Track generations for the reload trigger

        chapter_title_en = chapter_lines[0]["nat"] if chapter_lines else chapter.file_name
        chapter_media_dir.mkdir(exist_ok=True)

        safe_deck_title = sanitize_filename(novel_name).replace("_", " ")
        
        chapter_deck_id = get_deterministic_id(f"{novel_name}_Ch_{chapter.chapter_number}")
        chapter_deck = genanki.Deck(chapter_deck_id, f'{safe_deck_title}::Ch {chapter.chapter_number:03d}')
        #chapter_deck = genanki.Deck(chapter_deck_id, f'{novel_name} - Ch {chapter.chapter_number:03d}')
        chapter_media_files = [] 

        full_translated_text = ""
        epub_body_html = f"<h1>{chapter_title_en}</h1>\n"

        for line_idx, line in enumerate(chapter_lines):
            if stop_event.is_set(): break

            audio_filename = f"ch{chapter.chapter_number:02d}_L{line_idx:04d}.opus"
            audio_filepath = chapter_media_dir / audio_filename
            
            # --- STRICT AUDIO VALIDATION ---
            skip_audio = False
            if audio_filepath.exists():
                if audio_filepath.stat().st_size > 1024:
                    skip_audio = True
                else:
                    audio_filepath.unlink() 
            
            if not skip_audio:
                # --- NEW: AUTO-RELOAD EVERY 30 LINES ---
                if tts_model is not None and audio_count > 0 and audio_count % 30 == 0:
                    print(f"[SYSTEM] Auto-reloading TTS model to clear VRAM fragmentation...")
                    del tts_model
                    gc.collect()
                    torch.cuda.empty_cache()
                    tts_model = None # Force reload below

                if tts_model is None:
                    print(f"[SYSTEM] Loading Qwen3-TTS ({TTS_MODEL})...")
                    tts_model = Qwen3TTSModel.from_pretrained(
                        TTS_MODEL, 
                        device_map="cuda:0", 
                        dtype=torch.bfloat16, 
                        attn_implementation="flash_attention_2" 
                    )

                raw_text = clean_for_tts(line["cn"]) or "标题"
                emotion_tag = line.get("emo", "Calm narrative").strip()
                emotion_tag = re.sub(r'[^a-zA-Z0-9\s]', '', emotion_tag).strip()

                if len(emotion_tag.split()) > 6: emotion_tag = "Calm narrative"
                
                print(f"    [Audio] L{line_idx+1}/{len(chapter_lines)}: [{emotion_tag}] {raw_text[:40]}...")
                
                with torch.no_grad():
                    wavs, sr = tts_model.generate_custom_voice(
                        text=raw_text, 
                        language="Chinese", 
                        speaker=SPEAKER_VOICE, 
                        instruct=f"{emotion_tag}"
                    )
                
                # Validation & Deep Copy
                if torch.is_tensor(wavs[0]):
                    audio_tensor = wavs[0]
                    if audio_tensor.numel() == 0 or torch.isnan(audio_tensor).any() or torch.isinf(audio_tensor).any():
                        print(f"    [!] Corrupted audio detected at L{line_idx+1}. Writing silence.")
                        audio_data = np.zeros(int(sr * 1.0), dtype=np.float32)
                    else:
                        audio_data = (
                            audio_tensor
                            .detach()
                            .cpu()
                            .to(torch.float32)
                            .contiguous()
                            .numpy()
                            .copy()
                        )
                else:
                    audio_data = np.asarray(wavs[0], dtype=np.float32).copy()

                sf.write(str(audio_filepath), audio_data, sr, format='OGG', subtype='OPUS')
                
                # Nuke memory for this specific loop
                del wavs, audio_data
                gc.collect()
                torch.cuda.empty_cache()

                audio_count += 1 # Increment tracker

            chapter_media_files.append(str(audio_filepath))
            if str(audio_filepath) not in media_files_for_anki:
                media_files_for_anki.append(str(audio_filepath))

            card_guid_string = f"{novel_name}_Ch_{chapter.chapter_number:03d}_L{line_idx:04d}"
            card_guid = genanki.guid_for(card_guid_string)

            note = genanki.Note(
                model=ANKI_MODEL, guid=card_guid, 
                fields=[line["cn"], line["py"], line["lit"], line["nat"], f"[sound:{audio_filename}]"], 
                tags=[novel_name, f"Ch_{chapter.chapter_number:03d}"]
            )

            chapter_deck.add_note(note)
            #my_deck.add_note(note)

            full_translated_text += line["nat"] + "\n"
            epub_body_html += f"""
            <div class="study-block">
                <p class="cn">{line["cn"]}</p>
                <p class="py">{line["py"]}</p>
                <p class="lit">"{line["lit"]}"</p>
                <p class="en">{line["nat"]}</p>
                <audio controls preload="none"><source src="media/ch_{chapter.chapter_number:04d}/{audio_filename}" type="audio/ogg"></audio>
            </div>
            """

        if tts_model is not None:
            del tts_model
            gc.collect()
            torch.cuda.empty_cache()

        if stop_event.is_set(): return

        # --- STAGE 3: CHAPTER WRAP-UP ---
        
        # 1. Add this chapter to the master list
        all_chapter_decks.append(chapter_deck) 

        # 2. Export INDIVIDUAL Chapter Package (Just this specific chapter)
        # FIX: Use 'chapter_deck', NOT 'all_chapter_decks' here.
        ch_package = genanki.Package(chapter_deck)
        ch_package.media_files = chapter_media_files
        ch_package.write_to_file(str(ch_apkg_path))

        # 3. Write Text & XHTML
        (trans_dir / chapter.file_name).write_text(full_translated_text, encoding='utf-8')
        epub_html_full = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_body_html}</body></html>"
        xhtml_path.write_text(epub_html_full, encoding='utf-8')
        
        print(f"    [Export] Updating Master EPUB and Master Anki Deck...")
        metadata_file = novel_dir / "metadata.json"
        novel_metadata = json.loads(metadata_file.read_text(encoding='utf-8')) if metadata_file.exists() else {}
        
        raw_title = novel_metadata.get("title", novel_name)
        safe_title = sanitize_filename(raw_title)

        # 4. Build Master EPUB
        build_final_epub(safe_title, novel_dir, novel_metadata)
        
        # 5. Export MASTER Anki Package (All chapters processed so far)
        # FIX: Replaced 'my_deck' (which caused the crash) with 'all_chapter_decks'
        anki_package = genanki.Package(all_chapter_decks) 
        anki_package.media_files = media_files_for_anki
        anki_package.write_to_file(str(novel_dir / (safe_title + ".apkg")))

        print(f"✓ {chapter.file_name} successfully finished and exported.")

    print(f"\n[✓] PIPELINE COMPLETED SUCCESSFULLY.")
