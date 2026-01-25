# shell.nix for Qwen2.5-14B (LLM) + Qwen3-TTS (Source) + Anki Generator GUI
let
  pkgs = import <nixpkgs> { config.allowUnfree = true; };
  ccLib = pkgs.stdenv.cc.cc;

in pkgs.mkShell {
  packages = [
    # 1. Use the standard pre-compiled Python 3.10
    pkgs.python310 
    # 2. Add Tkinter as a separate pre-compiled package
    pkgs.python310Packages.tkinter 
    
    pkgs.uv
    pkgs.gcc
    pkgs.git
    pkgs.ffmpeg
    pkgs.libsndfile
    pkgs.sox
    pkgs.zlib
    pkgs.tk 
    pkgs.xorg.libX11 
    pkgs.cudaPackages.cudatoolkit
    (pkgs.ollama.override { acceleration = "cuda"; })
    ccLib
  ];

  shellHook = ''
    export LD_LIBRARY_PATH=/run/opengl-driver/lib:${ccLib.lib}/lib:${pkgs.libsndfile.out}/lib:${pkgs.zlib}/lib:${pkgs.cudaPackages.cudatoolkit}/lib:${pkgs.tk}/lib${":$LD_LIBRARY_PATH"}

    if ! pgrep -x "ollama" > /dev/null; then
        echo "Starting Ollama server..."
        ollama serve > ollama.log 2>&1 &
        sleep 2
    fi

    if [ ! -d ".venv" ]; then
        echo "Creating Python 3.10 virtual environment..."
        # Using standard python3.10 here since Tkinter is in the system path
        uv venv --python ${pkgs.python310}/bin/python 
        source .venv/bin/activate
        
        echo "1/5 Installing PyTorch with CUDA 12.4..."
        uv pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124

        echo "2/5 Installing Flash-Attention 2..."
        uv pip install https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.2.post1/flash_attn-2.7.2.post1+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl

        echo "3/5 Cloning Qwen3-TTS Repository..."
        if [ ! -d "Qwen3-TTS" ]; then
            git clone https://github.com/QwenLM/Qwen3-TTS.git
        fi

        echo "4/5 Installing Qwen3-TTS from source..."
        cd Qwen3-TTS
        uv pip install -e .
        cd ..

        echo "5/5 Installing GUI & Anki dependencies..."
        uv pip install ollama genanki rich ebooklib soundfile pydub customtkinter pillow
    else
        source .venv/bin/activate
    fi

    export PS1="\n\[\033[1;36m\][Qwen_GUI_Env:\w]\$\[\033[0m\] "
    echo "Environment ready! Run 'python gui.py' to launch the app."
  '';
}
