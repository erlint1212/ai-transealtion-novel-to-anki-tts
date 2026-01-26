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
from utils import Chapter, extract_chapter_number, chunk_text_into_numbered_lines, get_relevant_glossary, call_llm, parse_numbered_output, clean_for_tts
from prompts import prompt_json, prompt_natural, prompt_literal, prompt_pinyin, prompt_emotion
from exporters import build_final_epub

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

    deck_id = get_deterministic_id(novel_name)
    my_deck = genanki.Deck(deck_id, f'{novel_name} Vocab & Audio')
    
    # Pre-load existing media into the master Anki tracker
    media_files_for_anki = []
    for existing_audio in media_dir.rglob("*.opus"):
        media_files_for_anki.append(str(existing_audio))
    
    all_raw_files = sorted(raw_dir.glob("*.txt"))
    chapters = []
    for f in all_raw_files:
        ch_num = extract_chapter_number(f.name)
        if ch_num is not None and ch_num >= start_chapter:
            chapters.append(Chapter(novel_name, f.name, f.read_text(encoding='utf-8'), ch_num))

    print(f"Loaded {len(chapters)} chapters for processing.")

    # --- MAIN PROCESSING LOOP (ONE CHAPTER AT A TIME) ---
    for chapter in chapters:
        if stop_event.is_set(): return

        xhtml_filename = chapter.file_name.replace('.txt', '.xhtml')
        if (epub_dir / xhtml_filename).exists():
            print(f">>> SKIPPING {chapter.file_name} (Already 100% Complete).")
            continue
            
        print(f"\n{'='*50}\n>>> PROCESSING: {chapter.file_name}\n{'='*50}")
        
        # --- STAGE 1: LLM TRANSLATION ---
        print("\n--- STAGE 1: TEXT GENERATION ---")
        chunks = chunk_text_into_numbered_lines(chapter.content)
        chapter_lines = []
        chapter_cache_dir = cache_dir / f"ch_{chapter.chapter_number:04d}"
        chapter_cache_dir.mkdir(exist_ok=True)
        
        for i, chunk_dict in enumerate(chunks):
            if stop_event.is_set(): return
            chunk_size = len(chunk_dict)
            
            chunk_cache_file = chapter_cache_dir / f"chunk_{i:04d}.json"
            if chunk_cache_file.exists():
                print(f"    - Chunk {i+1}/{len(chunks)}: Loaded from cache.")
                chapter_lines.extend(json.loads(chunk_cache_file.read_text(encoding='utf-8')))
                continue

            print(f"    - Chunk {i+1}/{len(chunks)} ({chunk_size} lines): Sending to LLM...")
            numbered_input = "\n".join([f"{idx}. {text}" for idx, text in chunk_dict.items()])
            
            t0 = time.time()
            
            # 1. Update Glossary
            res_json = call_llm(prompt_json(), numbered_input)
            try:
                json_str = res_json[res_json.find('{'):res_json.rfind('}')+1]
                new_entities = json.loads(json_str)
                for c_name, c_data in new_entities.get("characters", {}).items():
                    if c_name not in glossary["characters"]: 
                        print(f"      [Glossary] Found new character: {c_name}")
                        glossary["characters"][c_name] = c_data
                for p_name, p_data in new_entities.get("places", {}).items():
                    if p_name not in glossary["places"]: 
                        print(f"      [Glossary] Found new place: {p_name}")
                        glossary["places"][p_name] = p_data
                glossary_file.write_text(json.dumps(glossary, ensure_ascii=False, indent=4), encoding='utf-8')
            except Exception: pass

            # 2. Extract Translations
            chunk_glossary = get_relevant_glossary(numbered_input, glossary)
            nat_dict = {idx: "" for idx in range(1, chunk_size + 1)}
            lit_dict = {idx: "" for idx in range(1, chunk_size + 1)}
            py_dict  = {idx: "" for idx in range(1, chunk_size + 1)}
            emo_dict = {idx: "Calm narrative" for idx in range(1, chunk_size + 1)}

            try: nat_dict.update(parse_numbered_output(call_llm(prompt_natural(chunk_glossary), numbered_input), chunk_size))
            except: print("      [!] Warning: Natural translation failed.")
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

        if stop_event.is_set(): return

        # --- VRAM BRIDGE: UNLOAD LLM ---
        print("\n[SYSTEM] Unloading LLM to free VRAM for Audio...")
        ollama.generate(model=LLM_MODEL, prompt="", keep_alive=0)
        time.sleep(1)

        # --- STAGE 2: AUDIO & FILE GENERATION ---
        print("\n--- STAGE 2: AUDIO & COMPILATION ---")
        from qwen_tts import Qwen3TTSModel
        tts_model = None

        chapter_title_en = chapter_lines[0]["nat"] if chapter_lines else chapter.file_name
        chapter_media_dir = media_dir / f"ch_{chapter.chapter_number:04d}"
        chapter_media_dir.mkdir(exist_ok=True)
        
        chapter_deck_id = get_deterministic_id(f"{novel_name}_Ch_{chapter.chapter_number}")
        chapter_deck = genanki.Deck(chapter_deck_id, f'{novel_name} - Ch {chapter.chapter_number:03d}')
        chapter_media_files = [] 

        full_translated_text = ""
        epub_body_html = f"<h1>{chapter_title_en}</h1>\n"

        for line_idx, line in enumerate(chapter_lines):
            if stop_event.is_set(): break

            audio_filename = f"ch{chapter.chapter_number:02d}_L{line_idx:04d}.opus"
            audio_filepath = chapter_media_dir / audio_filename
            
            if not audio_filepath.exists():
                if tts_model is None:
                    print(f"[SYSTEM] Loading Qwen3-TTS ({TTS_MODEL})...")
                    tts_model = Qwen3TTSModel.from_pretrained(TTS_MODEL, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="flash_attention_2")

                raw_text = clean_for_tts(line["cn"]) or "标题"
                emotion_tag = line.get("emo", "Calm narrative").strip()
                tts_text_with_emotion = f"({emotion_tag}) {raw_text}"
                
                print(f"    [Audio] L{line_idx+1}/{len(chapter_lines)}: {tts_text_with_emotion[:40]}...")
                wavs, sr = tts_model.generate_custom_voice(text=tts_text_with_emotion, language="Chinese", speaker=SPEAKER_VOICE)
                sf.write(str(audio_filepath), wavs[0], sr, format='OGG', subtype='OPUS')

                # --- NEW: AGGRESSIVE MEMORY CLEANUP ---
                # Delete the massive audio tensor from VRAM immediately after saving
                del wavs 
                gc.collect()
                torch.cuda.empty_cache() 

            # Tracking Media
            chapter_media_files.append(str(audio_filepath))
            if str(audio_filepath) not in media_files_for_anki:
                media_files_for_anki.append(str(audio_filepath))

            # HTML and Anki Building
            card_guid_string = f"{novel_name}_Ch_{chapter.chapter_number:03d}_L{line_idx:04d}"
            card_guid = genanki.guid_for(card_guid_string)

            note = genanki.Note(
                model=ANKI_MODEL, guid=card_guid, 
                fields=[line["cn"], line["py"], line["lit"], line["nat"], f"[sound:{audio_filename}]"], 
                tags=[novel_name, f"Ch_{chapter.chapter_number:03d}"]
            )
            chapter_deck.add_note(note)
            my_deck.add_note(note)

            full_translated_text += line["nat"] + "\n"
            epub_body_html += f"""
            <div class="study-block">
                <p class="cn">{line["cn"]} <span style="font-size:0.5em; color:#888;">[{line.get('emo', 'Calm')}]</span></p>
                <p class="py">{line["py"]}</p>
                <p class="lit">"{line["lit"]}"</p>
                <p class="en">{line["nat"]}</p>
                <audio controls preload="none"><source src="media/ch_{chapter.chapter_number:04d}/{audio_filename}" type="audio/ogg"></audio>
            </div>
            """

        # --- VRAM BRIDGE: UNLOAD TTS ---
        if tts_model is not None:
            del tts_model
            gc.collect()
            torch.cuda.empty_cache()

        if stop_event.is_set(): return

        # --- STAGE 3: CHAPTER WRAP-UP ---
        # 1. Save Isolated Chapter Deck
        ch_apkg_path = anki_ch_dir / f"Ch_{chapter.chapter_number:03d}.apkg"
        ch_package = genanki.Package(chapter_deck)
        ch_package.media_files = chapter_media_files
        ch_package.write_to_file(str(ch_apkg_path))

        # 2. Save HTML for the EPUB
        (trans_dir / chapter.file_name).write_text(full_translated_text, encoding='utf-8')
        epub_html_full = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{epub_body_html}</body></html>"
        xhtml_filename = chapter.file_name.replace('.txt', '.xhtml')
        (epub_dir / xhtml_filename).write_text(epub_html_full, encoding='utf-8')
        
        # 3. Compile Master EPUB and Master Anki Deck (Incremental Update)
        print(f"    [Export] Updating Master EPUB and Master Anki Deck...")
        metadata_file = novel_dir / "metadata.json"
        novel_metadata = json.loads(metadata_file.read_text(encoding='utf-8')) if metadata_file.exists() else {}
        build_final_epub(novel_name, novel_dir, novel_metadata)
        
        anki_package = genanki.Package(my_deck)
        anki_package.media_files = media_files_for_anki
        master_deck_name = novel_metadata.get("title", novel_name) + ".apkg"
        anki_package.write_to_file(str(novel_dir / master_deck_name))

        print(f"✓ {chapter.file_name} successfully finished and exported.")

    print(f"\n[✓] PIPELINE COMPLETED SUCCESSFULLY.")
