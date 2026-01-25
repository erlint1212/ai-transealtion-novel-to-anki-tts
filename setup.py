import os
import sys
import subprocess
import platform

def run_command(command, cwd=None):
    print(f"\n>>> Running: {' '.join(command)}")
    subprocess.check_call(command, cwd=cwd)

def setup():
    system = platform.system()
    print(f"--- 🚀 DETECTED PLATFORM: {system} ---")

    # 1. Install Flash-Attention 2 (Linux Only - Windows defaults to standard attention)
    if system == "Linux":
        print("\n--- 1/3: Installing Flash-Attention 2 (Linux) ---")
        run_command([
            sys.executable, "-m", "pip", "install",
            "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.2.post1/flash_attn-2.7.2.post1+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"
        ])
    else:
        print("\n--- 1/3: Skipping Flash-Attention (Not supported/needed on Windows) ---")

    # 2. Clone Qwen3-TTS
    print("\n--- 2/3: Cloning Qwen3-TTS ---")
    if not os.path.exists("Qwen3-TTS"):
        run_command(["git", "clone", "https://github.com/QwenLM/Qwen3-TTS.git"])
    else:
        print("Qwen3-TTS already exists. Skipping clone.")

    # 3. Install Qwen3-TTS from Source
    print("\n--- 3/3: Installing Qwen3-TTS ---")
    run_command([sys.executable, "-m", "pip", "install", "-e", "."], cwd="Qwen3-TTS")

    print("\n✅ Setup Complete! You can now run 'python gui.py'")

if __name__ == "__main__":
    setup()
