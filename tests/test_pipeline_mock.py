import unittest
import shutil
import json
import sys
import types
import importlib.machinery 
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
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

from main import process_novel

class TestMockPipeline(unittest.TestCase):
    def setUp(self):
        """Setup a temporary dummy novel directory."""
        self.test_root = Path("Novels_Test_Env")
        self.novel_name = "Mock_Novel_CI"
        self.novel_dir = self.test_root / self.novel_name
        self.raw_dir = self.novel_dir / "01_Raw_Text"
        
        # Clean start
        if self.test_root.exists(): shutil.rmtree(self.test_root)
        
        self.raw_dir.mkdir(parents=True)
        (self.novel_dir / "metadata.json").write_text('{"title": "Mock Book"}', encoding='utf-8')
        
        # Create a tiny dummy chapter
        (self.raw_dir / "ch_001.txt").write_text(
            "Hello world.\nThis is a test line for CI.", encoding='utf-8'
        )

    def tearDown(self):
        """Clean up the mess after testing."""
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    @patch('main.call_llm')       # 1. Mock the LLM Network Call
    @patch('main.Qwen3TTSModel')  # 2. Mock the Heavy TTS Class
    @patch('main.ollama')         # 3. Mock the Ollama Library
    def test_full_pipeline_flow(self, mock_ollama, mock_tts_class, mock_call_llm):
        
        # --- A. Setup LLM Mock Responses ---
        mock_json_resp = '{"characters": {}, "places": {}}'
        mock_nat_resp = "1. Hello world.\n2. This is a test line for CI."
        mock_lit_resp = "1. Literal Hello.\n2. Literal Test."
        mock_emo_resp = "1. Calm narrative\n2. Excited shouting"

        mock_call_llm.side_effect = [
            mock_json_resp, # Glossary Prompt
            mock_nat_resp,  # Natural Prompt
            mock_lit_resp,  # Literal Prompt
            mock_emo_resp   # Emotion Prompt
        ]

        # --- B. Setup TTS Mock ---
        mock_tts_instance = mock_tts_class.from_pretrained.return_value
        # Return 1 second of silence (NumPy array)
        dummy_audio = np.zeros((1, 24000), dtype=np.float32)
        mock_tts_instance.generate_custom_voice.return_value = (dummy_audio, 24000)

        # --- C. Run the Actual Pipeline ---
        stop_event = threading.Event()
        
        # We pass self.novel_dir directly
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

        print("\n✅ Mock CI Pipeline Test Passed!")

if __name__ == '__main__':
    unittest.main()
