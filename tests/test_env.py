import sys
import subprocess

def print_status(component, success, message=""):
    status = "✅ PASS" if success else "❌ FAIL"
    color = "\033[92m" if success else "\033[91m"
    print(f"{color}{status} | {component}{' - ' + message if message else ''}\033[0m")

print("\n--- 🔍 TESTING NIXOS AI ENVIRONMENT ---\n")

# 1. Test Python Version
print_status("Python 3.11", sys.version_info >= (3, 11), f"Found {sys.version.split()[0]}")

# 2. Test Package Imports
try:
    import ollama
    import genanki
    import rich
    print_status("Python Packages", True, "ollama, genanki, rich imported successfully")
except ImportError as e:
    print_status("Python Packages", False, str(e))

# 3. Test GPU CUDA Detection
try:
    smi = subprocess.check_output("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True).decode()
    print_status("CUDA / GPU", True, smi.strip())
except Exception:
    print_status("CUDA / GPU", False, "Could not communicate with NVIDIA GPU")

# 4. Test Ollama Daemon & Model
try:
    # Get the list of models
    response = ollama.list()
    
    # In the latest SDK, response.models is a list of objects
    model_names = [m.model for m in response.models]
    
    # Check if our specific Qwen model is in the list
    target_model = "qwen2.5:14b-instruct-q5_K_M"
    model_found = target_model in model_names
    
    print_status("Ollama Daemon", True, "Server is running and responding")
    print_status("Qwen2.5 Model", model_found, f"Model '{target_model}' is ready" if model_found else f"Model not found. Available: {', '.join(model_names)}")

except Exception as e:
    print_status("Ollama Daemon", False, f"Error communicating with server: {str(e)}")

print("\n----------------------------------------\n")
