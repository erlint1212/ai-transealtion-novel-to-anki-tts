# 📚 Novel to Anki & Ebook with Audio Generator

An automated, locally-hosted AI pipeline that transforms raw Chinese web novels into rich, multimedia flashcards and immersive EPUB audiobooks. 

Designed for language learners, this tool uses **Local LLMs (Qwen2.5-14B)** and state-of-the-art **Text-to-Speech (Qwen3-TTS)** to dissect novels line-by-line, extract vocabulary, generate translations, and synthesize ultra-realistic Chinese audio—all running 100% locally on your hardware.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)
![PyTorch](https://img.shields.io/badge/PyTorch-2.5.1%20CUDA%2012.4-orange)
![Platform](https://img.shields.io/badge/platform-NixOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

---

## 🎯 Motivation

Language learning is often hindered by a lack of context. Learning individual words in isolation is inefficient and robotic.

This project was built to automate the **"Sentence Mining"** method championed by polyglots and Dr. Taylor Jones. The core philosophy is **Contextual Acquisition**:
1.  **Sentence > Word:** Learning a word inside a sentence teaches grammar, nuance, and usage simultaneously.
2.  **Audio Prosody:** Hearing a full sentence spoken with emotion creates stronger memory hooks than robotic, single-word audio.
3.  **i+1 Learning:** By breaking a novel into lines, the material is manageable yet challenging, allowing for natural language acquisition through immersion.

This tool removes the hundreds of hours of manual labor required to create sentence cards, letting you focus entirely on reading and listening.

---

## ✨ Features

* **🧠 Smart Dual-AI Pipeline:** Uses `Qwen2.5-14B` for high-quality translation and `Qwen3-TTS (1.7B)` for lifelike text-to-speech.
* **⚡ VRAM Safety Bridge:** Intelligently unloads the 10GB LLM from GPU memory before loading the 4GB TTS model, allowing massive pipelines to run on standard 12GB consumer GPUs (like the RTX 4080).
* **📖 Dynamic Glossary Extraction:** The AI acts as a lore-master, tracking characters and locations in a `glossary.json` to ensure translation consistency across hundreds of chapters.
* **🖥️ Multi-Threaded GUI:** A sleek CustomTkinter interface that prevents system freezing, with live verbose logging and a fail-safe "Terminate" hook.
* **💻 Headless CLI:** A command-line interface for server deployments or power users.
* **🎵 Opus Audio Compression:** Squeezes thousands of audio files into OGG/OPUS format, saving up to 90% space with zero loss in vocal fidelity.
* **📦 Polished Exports:** * **Anki Decks (`.apkg`):** Hierarchical subdecks (by chapter) with native Audio, Pinyin, Literal Translation, and Natural English.
    * **E-Books (`.epub`):** Beautifully styled chapters with "Dark Mode" support and embedded HTML5 `<audio>` tags.

---

## 🚀 Quick Start

This project is built to be cross-platform using **Conda**. FFmpeg, CUDA drivers, and Tkinter are all handled automatically.

### 1. Install & Setup
Requires [Miniconda](https://docs.anaconda.com/free/miniconda/index.html) or NixOS.

```bash
# Clone the repository
git clone git@github.com:erlint1212/ai-transealtion-novel-to-anki-tts.git
cd ai-transealtion-novel-to-anki-tts

# Create the environment with all system dependencies (FFmpeg, CUDA, Tkinter)
conda env create -f environment.yml
conda activate qwen_anki_env

# Run the setup script to install Flash-Attention 2 and Qwen3-TTS
python setup.py

```

### 2. Prepare the AI Server

You must have [Ollama](https://ollama.com/) installed and running in the background. Pull the required translation model:

```bash
ollama pull qwen2.5:14b-instruct-q5_K_M

```

---

## 🕹️ Usage

### 1. File Preparation

Drop your novel into the `Novels/` directory. The structure should look like this:

```text
Novels/
└── Novel_Title/
    ├── metadata.json           # (Optional) Book Title, Author, Cover info
    ├── cover.jpg               # (Optional) High-res cover art
    └── 01_Raw_Text/
        ├── ch_0001.txt
        └── ch_0002.txt

```

### 2. Running the Tool

#### Option A: Graphical Interface (Recommended)

Launch the visual dashboard to select chapters, edit metadata, and view logs.

```bash
python gui.py

```

#### Option B: Command Line Interface (Headless)

Run the pipeline directly from the terminal.

```bash
# List available novels
python cli.py --list

# Process a specific novel starting from Chapter 419
python cli.py Novel_Title --ch 419

```

### 3. Studying

* **Anki:** Import the generated `.apkg` file. The deck uses **Hierarchical Tags**, so you can expand the novel name and study specific chapters (e.g., `Novel::Ch 0419`).
* **EPUB:** Open the `.epub` file in Apple Books, Moon+ Reader, or Calibre. The text colors are optimized for both Light and Dark modes.

---

## 🏗️ Architecture

The codebase is modularized for extensibility and fault tolerance:

* `gui.py`: Multi-threaded Tkinter orchestrator with live terminal redirection.
* `cli.py`: Command-line entry point with safe shutdown handling.
* `main.py`: The core pipeline (Chunking -> Translation -> VRAM Flush -> Audio Gen -> Compilation).
* `utils.py`: Text sanitization regex and JSON-parsing logic.
* `prompts.py`: Few-shot prompts for precise entity extraction.
* `exporters.py`: EPUB manifest generation and Anki packaging.

---

## 🛠️ Technical Highlights for Developers

* **Flash-Attention 2 Integration:** Audio synthesis is accelerated using Dao-AILab's Flash-Attention, achieving sub-second speech synthesis on modern NVIDIA hardware.
* **Just-In-Time (JIT) Context Filtering:** The LLM does not ingest the entire glossary for every query. Instead, Python pre-scans the text and injects a "micro-glossary" of only relevant entities into the prompt, saving tokens and improving speed.
* **Smart Caching:** The pipeline saves translation chunks as JSON. If the script crashes, it resumes exactly where it left off without re-translating.
* **Thread-Safe UI:** The GUI uses queue-based updates to prevent Tkinter race conditions during heavy background processing.

---

## 🤝 Contributing

Contributions are welcome! If you have ideas for new features or bug fixes:

1. **Fork** the repository.
2. Create a new **Branch** (`git checkout -b feature/AmazingFeature`).
3. **Commit** your changes (`git commit -m 'Add some AmazingFeature'`).
4. **Push** to the branch (`git push origin feature/AmazingFeature`).
5. Open a **Pull Request**.

Please ensure you run the unit tests before submitting:

```bash
python -m unittest discover tests/

```

---

## 🙏 Acknowledgments

This project was heavily inspired by **Dr. Taylor Jones's (Language Jones)** fantastic video, ["The BEST way to learn a language QUICKLY with books"](https://www.youtube.com/watch?v=QVpu66njzdE), which outlines the neuroscience and efficacy behind using local text-to-speech tools and Anki sentence mining for language acquisition.

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

*Note: The generated audio and translations are for personal educational use. Please respect the copyright of the original novel authors.*

```
