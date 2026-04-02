import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

# Local Imports
from config import (
    BACKENDS,
    NOVELS_ROOT_DIR,
    get_backend_name,
    get_llm_model,
    set_backend,
    set_llm_model,
)
from main import process_novel
from utils import extract_chapter_number, list_models

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Save original streams so we can still print to the Konsole
original_stdout = sys.stdout
original_stderr = sys.stderr

# Regex to find terminal color codes
ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

NO_MODELS_TEXT = "No models found"


class TextRedirector:
    def __init__(self, text_widget, original_stream):
        self.text_widget = text_widget
        self.original_stream = original_stream

    def write(self, text):
        self.original_stream.write(text)
        clean_text = ansi_escape.sub("", text)
        self.text_widget.after(0, self._update_gui, clean_text)

    def _update_gui(self, text):
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", text)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")

    def flush(self):
        self.original_stream.flush()


class NovelApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("NixOS AI: Novel & Audio Generator")
        self.geometry("1200x800")

        # Thread & State Control
        self.ai_thread = None
        self.stop_event = threading.Event()
        self.current_cover_path = None

        # --- LAYOUT SETUP ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ====================
        # 1. LEFT SIDEBAR
        # ====================
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(9, weight=1)  # Spacer row

        ctk.CTkLabel(
            self.sidebar, text="Configuration", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10))

        # ---- LLM Backend Selection ----
        ctk.CTkLabel(self.sidebar, text="LLM Backend:").grid(
            row=1, column=0, columnspan=2, padx=20, pady=(10, 0), sticky="w"
        )
        self.backend_var = ctk.StringVar(value=get_backend_name())
        self.backend_dropdown = ctk.CTkOptionMenu(
            self.sidebar,
            variable=self.backend_var,
            values=list(BACKENDS.keys()),
            command=self.on_backend_change,
        )
        self.backend_dropdown.grid(
            row=2, column=0, columnspan=2, padx=20, pady=(5, 10), sticky="ew"
        )

        # ---- Model Selection + Refresh ----
        ctk.CTkLabel(self.sidebar, text="Model:").grid(
            row=3, column=0, columnspan=2, padx=20, pady=(5, 0), sticky="w"
        )

        # Frame to hold the model dropdown + refresh button side by side
        self.model_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.model_frame.grid(
            row=4, column=0, columnspan=2, padx=20, pady=(5, 10), sticky="ew"
        )
        self.model_frame.grid_columnconfigure(0, weight=1)

        self.model_var = ctk.StringVar(value=NO_MODELS_TEXT)
        self.model_dropdown = ctk.CTkOptionMenu(
            self.model_frame,
            variable=self.model_var,
            values=[NO_MODELS_TEXT],
            command=self.on_model_change,
        )
        self.model_dropdown.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.refresh_btn = ctk.CTkButton(
            self.model_frame,
            text="⟳",
            width=36,
            command=self.refresh_models,
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e")

        # ---- Novel Selection ----
        ctk.CTkLabel(self.sidebar, text="Select Novel:").grid(
            row=5, column=0, columnspan=2, padx=20, pady=(10, 0), sticky="w"
        )
        self.novel_var = ctk.StringVar()
        self.novel_dropdown = ctk.CTkOptionMenu(
            self.sidebar, variable=self.novel_var, command=self.on_novel_change
        )
        self.novel_dropdown.grid(
            row=6, column=0, columnspan=2, padx=20, pady=(5, 10), sticky="ew"
        )

        # ---- Chapter Selection ----
        ctk.CTkLabel(self.sidebar, text="Start From Chapter:").grid(
            row=7, column=0, columnspan=2, padx=20, pady=(10, 0), sticky="w"
        )
        self.chapter_var = ctk.StringVar()
        self.chapter_dropdown = ctk.CTkOptionMenu(
            self.sidebar, variable=self.chapter_var
        )
        self.chapter_dropdown.grid(
            row=8, column=0, columnspan=2, padx=20, pady=(5, 10), sticky="ew"
        )

        # ---- Action Buttons ----
        self.start_btn = ctk.CTkButton(
            self.sidebar,
            text="▶ START PIPELINE",
            fg_color="green",
            hover_color="darkgreen",
            font=ctk.CTkFont(weight="bold"),
            command=self.start_processing,
        )
        self.start_btn.grid(
            row=10, column=0, columnspan=2, padx=20, pady=10, sticky="ew"
        )

        self.stop_btn = ctk.CTkButton(
            self.sidebar,
            text="⏹ TERMINATE",
            fg_color="red",
            hover_color="darkred",
            font=ctk.CTkFont(weight="bold"),
            state="disabled",
            command=self.stop_processing,
        )
        self.stop_btn.grid(
            row=11, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew"
        )

        # ====================
        # 2. MAIN AREA (TABS)
        # ====================
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.tab_logs = self.tabview.add("Execution Logs")
        self.tab_meta = self.tabview.add("Novel Metadata")

        # --- TAB 1: LOGS ---
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_logs.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(
            self.tab_logs,
            font=("Ubuntu Mono", 13),
            fg_color="#1e1e1e",
            text_color="#d4d4d4",
        )
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.log_textbox.configure(state="disabled")

        sys.stdout = TextRedirector(self.log_textbox, original_stdout)
        sys.stderr = TextRedirector(self.log_textbox, original_stderr)

        # --- TAB 2: METADATA EDITOR ---
        self.tab_meta.grid_columnconfigure(1, weight=1)
        self.tab_meta.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(self.tab_meta, text="Book Title:").grid(
            row=0, column=0, padx=10, pady=10, sticky="e"
        )
        self.meta_title = ctk.CTkEntry(
            self.tab_meta, placeholder_text="Translated English Title"
        )
        self.meta_title.grid(
            row=0, column=1, columnspan=2, padx=10, pady=10, sticky="ew"
        )

        ctk.CTkLabel(self.tab_meta, text="Author:").grid(
            row=1, column=0, padx=10, pady=10, sticky="e"
        )
        self.meta_author = ctk.CTkEntry(self.tab_meta, placeholder_text="Author Name")
        self.meta_author.grid(
            row=1, column=1, columnspan=2, padx=10, pady=10, sticky="ew"
        )

        ctk.CTkLabel(self.tab_meta, text="Language:").grid(
            row=2, column=0, padx=10, pady=10, sticky="e"
        )
        self.meta_lang = ctk.CTkEntry(self.tab_meta)
        self.meta_lang.insert(0, "en")
        self.meta_lang.grid(
            row=2, column=1, columnspan=2, padx=10, pady=10, sticky="ew"
        )

        ctk.CTkLabel(self.tab_meta, text="Description:").grid(
            row=3, column=0, padx=10, pady=10, sticky="ne"
        )
        self.meta_desc = ctk.CTkTextbox(self.tab_meta, height=150)
        self.meta_desc.grid(
            row=3, column=1, columnspan=2, padx=10, pady=10, sticky="nsew"
        )

        ctk.CTkLabel(self.tab_meta, text="Cover Image:").grid(
            row=4, column=0, padx=10, pady=10, sticky="e"
        )

        self.meta_cover_path = ctk.CTkEntry(
            self.tab_meta, placeholder_text="/home/user/Pictures/cover.jpg"
        )
        self.meta_cover_path.grid(row=4, column=1, padx=10, pady=10, sticky="ew")
        self.meta_cover_path.bind("<FocusOut>", self.apply_cover_from_path)
        self.meta_cover_path.bind("<Return>", self.apply_cover_from_path)

        self.btn_browse_cover = ctk.CTkButton(
            self.tab_meta, text="Browse...", width=80, command=self.browse_cover_image
        )
        self.btn_browse_cover.grid(row=4, column=2, padx=10, pady=10, sticky="w")

        self.cover_preview = ctk.CTkLabel(
            self.tab_meta,
            text="No Cover Image",
            width=150,
            height=225,
            fg_color="gray20",
            corner_radius=5,
        )
        self.cover_preview.grid(
            row=5, column=1, columnspan=2, padx=10, pady=10, sticky="w"
        )

        self.btn_save_meta = ctk.CTkButton(
            self.tab_meta,
            text="💾 Save Metadata",
            fg_color="#2b7bba",
            hover_color="#1c5582",
            command=self.save_metadata,
        )
        self.btn_save_meta.grid(
            row=6, column=1, columnspan=2, padx=10, pady=20, sticky="ew"
        )

        # Init
        self.load_novels()
        self.refresh_models()  # Fetch models for the default backend on launch

    # ==========================
    # BACKEND & MODEL LOGIC
    # ==========================
    def on_backend_change(self, backend_name):
        """Switch backend and refresh the model list."""
        try:
            set_backend(backend_name)
        except ValueError as e:
            print(f"[Error] {e}")
            return
        self.model_var.set("Loading...")
        self.model_dropdown.configure(values=["Loading..."])
        self.refresh_models()

    def on_model_change(self, model_name):
        """Set the active model when user picks from dropdown."""
        if model_name and model_name not in (NO_MODELS_TEXT, "Loading..."):
            set_llm_model(model_name)

    def refresh_models(self):
        """Fetch models from the active backend in a background thread."""
        self.refresh_btn.configure(state="disabled", text="...")

        def _fetch():
            models, error = list_models()
            # Schedule the UI update back on the main thread
            self.after(0, self._apply_model_list, models, error)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_model_list(self, models, error):
        """Update the model dropdown on the main thread after fetching."""
        self.refresh_btn.configure(state="normal", text="⟳")

        if error:
            print(f"[Backend] {error}")
            self.model_dropdown.configure(values=[NO_MODELS_TEXT])
            self.model_var.set(NO_MODELS_TEXT)
            return

        self.model_dropdown.configure(values=models)

        # Try to keep the current selection if it exists in the new list
        current = self.model_var.get()
        if current in models:
            self.model_var.set(current)
            set_llm_model(current)
        else:
            # Auto-select the first model
            self.model_var.set(models[0])
            set_llm_model(models[0])

        print(f"[Backend] Found {len(models)} model(s) on {get_backend_name()}")

    # ==========================
    # NOVEL / CHAPTER LOGIC
    # ==========================
    def load_novels(self):
        if not NOVELS_ROOT_DIR.exists():
            print(f"Error: {NOVELS_ROOT_DIR} not found.")
            return

        novels = [
            d.name
            for d in NOVELS_ROOT_DIR.iterdir()
            if d.is_dir() and (d / "01_Raw_Text").exists()
        ]
        if novels:
            self.novel_dropdown.configure(values=novels)
            self.novel_var.set(novels[0])
            self.on_novel_change(novels[0])
        else:
            self.novel_dropdown.configure(values=["No Novels Found"])
            self.novel_var.set("No Novels Found")

    def on_novel_change(self, novel_name):
        raw_dir = NOVELS_ROOT_DIR / novel_name / "01_Raw_Text"
        if raw_dir.exists():
            files = sorted(raw_dir.glob("*.txt"))
            chapters = []
            for f in files:
                ch_num = extract_chapter_number(f.name)
                if ch_num is not None:
                    chapters.append(f"Ch {ch_num:03d}")
            if chapters:
                self.chapter_dropdown.configure(values=chapters)
                self.chapter_var.set(chapters[0])
            else:
                self.chapter_dropdown.configure(values=["No Chapters"])
                self.chapter_var.set("No Chapters")

        self.load_metadata(novel_name)

    def load_metadata(self, novel_name):
        novel_dir = NOVELS_ROOT_DIR / novel_name
        meta_file = novel_dir / "metadata.json"

        self.meta_title.delete(0, "end")
        self.meta_author.delete(0, "end")
        self.meta_lang.delete(0, "end")
        self.meta_desc.delete("0.0", "end")
        self.meta_cover_path.delete(0, "end")
        self.cover_preview.configure(image=None, text="No Cover Image")
        self.current_cover_path = None

        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                self.meta_title.insert(0, data.get("title", ""))
                self.meta_author.insert(0, data.get("author", ""))
                self.meta_lang.insert(0, data.get("language", "en"))
                self.meta_desc.insert("0.0", data.get("description", ""))

                cover_filename = data.get("cover_image", "")
                if cover_filename:
                    cover_path = novel_dir / cover_filename
                    if cover_path.exists():
                        self.meta_cover_path.insert(0, str(cover_path.absolute()))
                        self.display_cover_preview(cover_path)
            except Exception as e:
                print(f"Error loading metadata: {e}")

    def browse_cover_image(self):
        file_path = filedialog.askopenfilename(
            title="Select Cover Image",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png")],
        )
        if file_path:
            self.meta_cover_path.delete(0, "end")
            self.meta_cover_path.insert(0, file_path)
            self.apply_cover_from_path()

    def apply_cover_from_path(self, event=None):
        path_str = self.meta_cover_path.get().strip()
        path_str = path_str.replace('"', "").replace("'", "")

        if not path_str:
            return

        img_path = Path(path_str)
        if img_path.exists() and img_path.is_file():
            self.current_cover_path = img_path
            self.display_cover_preview(img_path)
        else:
            self.cover_preview.configure(image=None, text="[!] File Not Found")
            self.current_cover_path = None

    def display_cover_preview(self, img_path):
        try:
            pil_image = Image.open(img_path)
            ctk_image = ctk.CTkImage(
                light_image=pil_image, dark_image=pil_image, size=(150, 225)
            )
            self.cover_preview.configure(image=ctk_image, text="")
        except Exception as e:
            self.cover_preview.configure(image=None, text="[!] Invalid Image")
            print(f"Error displaying image: {e}")

    def save_metadata(self):
        novel_name = self.novel_var.get()
        if "No" in novel_name:
            return

        novel_dir = NOVELS_ROOT_DIR / novel_name
        cover_filename = ""

        if self.current_cover_path and self.current_cover_path.exists():
            if self.current_cover_path.parent != novel_dir:
                ext = self.current_cover_path.suffix
                new_cover_path = novel_dir / f"cover{ext}"
                shutil.copy2(self.current_cover_path, new_cover_path)
                cover_filename = f"cover{ext}"
                print(f"[Metadata] Imported new cover image: {cover_filename}")
            else:
                cover_filename = self.current_cover_path.name

        meta_data = {
            "title": self.meta_title.get(),
            "author": self.meta_author.get(),
            "language": self.meta_lang.get(),
            "description": self.meta_desc.get("0.0", "end-1c"),
            "cover_image": cover_filename,
        }

        meta_file = novel_dir / "metadata.json"
        meta_file.write_text(
            json.dumps(meta_data, indent=4, ensure_ascii=False), encoding="utf-8"
        )

        self.btn_save_meta.configure(text="✅ Saved!", fg_color="green")
        self.after(
            2000,
            lambda: self.btn_save_meta.configure(
                text="💾 Save Metadata", fg_color="#2b7bba"
            ),
        )
        print(f"[Metadata] Saved metadata.json for '{novel_name}'.")

    # ==========================
    # PIPELINE THREADING
    # ==========================
    def start_processing(self):
        # Validate a real model is selected
        current_model = self.model_var.get()
        if current_model in (NO_MODELS_TEXT, "Loading...", ""):
            print("[Error] No model selected. Select a model or hit ⟳ to refresh.")
            return

        self.tabview.set("Execution Logs")
        novel_name = self.novel_var.get()
        ch_str = self.chapter_var.get()

        if "No" in novel_name or "No" in ch_str:
            return
        start_ch = int(ch_str.split(" ")[1])

        # Lock all controls
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.novel_dropdown.configure(state="disabled")
        self.chapter_dropdown.configure(state="disabled")
        self.backend_dropdown.configure(state="disabled")
        self.model_dropdown.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")
        self.stop_event.clear()

        novel_dir = NOVELS_ROOT_DIR / novel_name
        self.ai_thread = threading.Thread(
            target=self.run_ai, args=(novel_dir, start_ch), daemon=True
        )
        self.ai_thread.start()

    def run_ai(self, novel_dir, start_ch):
        try:
            model_name = get_llm_model()
            print(
                f"\n{'='*50}\n"
                f"Starting pipeline for '{novel_dir.name}' at Chapter {start_ch}\n"
                f"Backend: {get_backend_name()} | Model: {model_name}\n"
                f"{'='*50}"
            )
            process_novel(novel_dir, start_ch, self.stop_event)
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
        finally:
            if self.stop_event.is_set():
                print("\n[!] PROCESS TERMINATED BY USER.")
            else:
                print("\n[✓] PIPELINE COMPLETED SUCCESSFULLY.")

            # Unlock all controls
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.novel_dropdown.configure(state="normal")
            self.chapter_dropdown.configure(state="normal")
            self.backend_dropdown.configure(state="normal")
            self.model_dropdown.configure(state="normal")
            self.refresh_btn.configure(state="normal")

    def stop_processing(self):
        print(
            "\n[!] Termination requested. Waiting for current chunk to finish safely..."
        )
        self.stop_btn.configure(state="disabled", text="Stopping...")
        self.stop_event.set()


if __name__ == "__main__":
    app = NovelApp()
    app.mainloop()
