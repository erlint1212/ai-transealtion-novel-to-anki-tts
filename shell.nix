# shell.nix for Qwen2.5-14B (LLM) + Anki Generator on NixOS 25.05
let
  pkgs = import <nixpkgs> { config.allowUnfree = true; };
  ccLib = pkgs.stdenv.cc.cc;
in pkgs.mkShell {
  packages = [
    pkgs.python311
    pkgs.uv
    pkgs.gcc
    pkgs.git
    pkgs.which
    pkgs.wget
    pkgs.cudaPackages.cudatoolkit
    pkgs.anki
    
    # Ollama built with CUDA support for NixOS
    (pkgs.ollama.override { acceleration = "cuda"; })
    ccLib
  ];

  shellHook = ''
    # Expose CUDA libraries to the environment
    export LD_LIBRARY_PATH=/run/opengl-driver/lib:${ccLib.lib}/lib:${pkgs.cudaPackages.cudatoolkit}/lib${":$LD_LIBRARY_PATH"}

    # Start Ollama in the background if it's not already running
    if ! pgrep -x "ollama" > /dev/null; then
        echo "Starting Ollama server in the background..."
        ollama serve > ollama.log 2>&1 &
        sleep 2 # Give it a moment to boot up
    fi

    # Set up the Python Environment with UV
    if [ ! -d ".venv" ]; then
        echo "Creating Python 3.11 virtual environment (.venv) with UV..."
        uv venv --python 3.11
        source .venv/bin/activate
        
        echo "Installing Python dependencies for Anki Generator..."
        # 'ollama' -> Official Python SDK to talk to the local model
        # 'genanki' -> Library to generate .apkg Anki decks
        # 'rich' -> For beautiful terminal outputs and loading spinners
        uv pip install ollama genanki rich ebooklib
    else
        source .venv/bin/activate
    fi

    # Ensure the specific Qwen2.5 14B model is downloaded
    echo "Checking for Qwen2.5-14B (Q5_K_M) model..."
    ollama pull qwen2.5:14b-instruct-q5_K_M

    export PS1="\n\[\033[1;35m\][Qwen_Anki_env:\w]\$\[\033[0m\] "
    echo "Environment ready! The RTX 4080 is primed for translation."
  '';
}
