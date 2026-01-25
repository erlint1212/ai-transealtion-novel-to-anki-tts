import sys
import subprocess

def print_status(component, success, message=""):
    status = "✅ PASS" if success else "❌ FAIL"
    color = "\033[92m" if success else "\033[91m"
    print(f"{color}{status} | {component}{' - ' + message if message else ''}\033[0m")

print("\n--- 🔍 TESTING ULTIMATE NIXOS AI ENVIRONMENT ---\n")

# 1. Test Python Version (Must be 3.10 for Flash-Attention)
is_310 = sys.version_info.major == 3 and sys.version_info.minor == 10
print_status("Python 3.10", is_310, f"Found {sys.version.split()[0]}")

# 2. Test Basic LLM/Anki Packages
try:
    import ollama
    import genanki
    import rich
    import ebooklib
    print_status("Basic Packages", True, "ollama, genanki, rich, ebooklib imported successfully")
except ImportError as e:
    print_status("Basic Packages", False, str(e))

# 3. Test GPU CUDA Detection (System Level)
try:
    smi = subprocess.check_output("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True).decode()
    print_status("CUDA / GPU (NVIDIA-SMI)", True, smi.strip())
except Exception:
    print_status("CUDA / GPU (NVIDIA-SMI)", False, "Could not communicate with NVIDIA GPU")

# 4. Test PyTorch & CUDA Integration
try:
    import torch
    cuda_available = torch.cuda.is_available()
    cuda_version = torch.version.cuda
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else "None"
    print_status("PyTorch CUDA", cuda_available, f"CUDA {cuda_version} detected. Using GPU: {gpu_name}")
except ImportError:
    print_status("PyTorch CUDA", False, "PyTorch not installed")

# 5. Test Flash-Attention
try:
    import flash_attn
    print_status("Flash-Attention 2", True, f"Version {flash_attn.__version__} installed")
except ImportError as e:
    print_status("Flash-Attention 2", False, "Not found. This usually fails if Python is not 3.10 or CUDA vars are missing.")

# 6. Test Qwen-TTS & Audio Packages
try:
    import soundfile
    import pydub
    from qwen_tts import Qwen3TTSModel
    print_status("Qwen3-TTS Module", True, "qwen_tts loaded successfully from source")
except ImportError as e:
    print_status("Qwen3-TTS Module", False, str(e))

# 7. Test Ollama Daemon & LLM
try:
    response = ollama.list()
    model_names = [m.model for m in response.models]
    target_model = "qwen2.5:14b-instruct-q5_K_M"
    model_found = target_model in model_names
    
    print_status("Ollama Daemon", True, "Server is running and responding")
    print_status("Qwen2.5 LLM", model_found, f"Model '{target_model}' is ready" if model_found else f"Model not found. Available: {', '.join(model_names)}")
except Exception as e:
    print_status("Ollama Daemon", False, f"Error communicating with server: {str(e)}")

print("\n-------------------------------------------------\n")
