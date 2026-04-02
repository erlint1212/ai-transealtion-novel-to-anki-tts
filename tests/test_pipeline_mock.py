import importlib.machinery
import json
import shutil
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

# ROBUST MOCK: Fake the Flash Attention module completely
# 1. Create the module object
mock_flash = types.ModuleType("flash_attn")
# 2. Give it a dummy spec so importlib.util.find_spec() doesn't crash
mock_flash.__spec__ = importlib.machinery.ModuleSpec(name="flash_attn", loader=None)
# 3. Register it in sys.modules
sys.modules["flash_attn"] = mock_flash

# Add parent dir to path so we can import main
sys.path.append(str(Path(__file__).parent.parent))

from config import set_backend, set_llm_model
from main import process_novel


class TestMockPipeline(unittest.TestCase):
    def setUp(self):
        """Setup a temporary dummy novel directory."""
        self.test_root = Path("Novels_Test_Env")
        self.novel_name = "Mock_Novel_CI"
        self.novel_dir = self.test_root / self.novel_name
        self.raw_dir = self.novel_dir / "01_Raw_Text"

        # Clean start
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

        self.raw_dir.mkdir(parents=True)
        (self.novel_dir / "metadata.json").write_text(
            '{"title": "Mock Book"}', encoding="utf-8"
        )

        # Create a tiny dummy chapter
        (self.raw_dir / "ch_001.txt").write_text(
            "Hello world.\nThis is a test line for CI.", encoding="utf-8"
        )

        # Set a mock backend and model so the pipeline doesn't error
        set_backend("Ollama")
        set_llm_model("mock-test-model")

    def tearDown(self):
        """Clean up the mess after testing."""
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    @patch("main.call_llm")        # 1. Mock the direct LLM call (glossary extraction)
    @patch("main.robust_parse")    # 2. Mock the validated LLM calls (nat, lit, emo)
    @patch("main.Qwen3TTSModel")   # 3. Mock the Heavy TTS Class
    @patch("main.unload_llm")      # 4. Mock VRAM unload (replaces old main.ollama)
    def test_full_pipeline_flow(self, mock_unload, mock_tts_class, mock_robust_parse, mock_call_llm):

        # --- A. Setup LLM Mock Responses ---
        # call_llm is used once per chunk for glossary extraction
        mock_call_llm.return_value = '{"characters": {}, "places": {}}'

        # robust_parse is called 3 times per chunk: natural, literal, emotion
        mock_robust_parse.side_effect = [
            {1: "Hello world.", 2: "This is a test line for CI."},
            {1: "Literal Hello.", 2: "Literal Test."},
            {1: "Calm narrative", 2: "Excited shouting"},
        ]

        # --- B. Setup TTS Mock ---
        mock_tts_instance = mock_tts_class.from_pretrained.return_value
        # Return 1 second of silence (NumPy array)
        dummy_audio = np.zeros((1, 24000), dtype=np.float32)
        mock_tts_instance.generate_custom_voice.return_value = (dummy_audio, 24000)

        # --- C. Run the Actual Pipeline ---
        stop_event = threading.Event()

        process_novel(self.novel_dir, 1, stop_event, redo_pinyin=False)

        # --- D. Assertions (Did it work?) ---
        self.assertTrue((self.novel_dir / "02_Translated").exists())
        self.assertTrue((self.novel_dir / "03_EPUB_Chapters").exists())
        self.assertTrue((self.novel_dir / "04_Anki_Chapters").exists())

        expected_epub = self.novel_dir / "Mock_Book.epub"
        expected_anki = self.novel_dir / "Mock_Book.apkg"

        self.assertTrue(expected_epub.exists(), "EPUB file was not created")
        self.assertTrue(expected_anki.exists(), "Anki package was not created")

        media_dir = self.novel_dir / "media" / "ch_0001"
        self.assertTrue(media_dir.exists())
        self.assertTrue(len(list(media_dir.glob("*.opus"))) > 0, "Audio files missing")

        # Verify mocks were called correctly
        mock_call_llm.assert_called_once()       # 1 glossary call
        self.assertEqual(mock_robust_parse.call_count, 3)  # nat + lit + emo
        mock_unload.assert_called_once()          # VRAM cleanup before TTS

        print("\n Mock CI Pipeline Test Passed!")


if __name__ == "__main__":
    unittest.main()
