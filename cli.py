import argparse
import signal
import sys
import threading
from pathlib import Path

# Local Imports
from config import BACKENDS, NOVELS_ROOT_DIR, console, set_backend, set_llm_model
from main import process_novel
from utils import list_models


def get_available_novels():
    if not NOVELS_ROOT_DIR.exists():
        return []
    return [
        d.name
        for d in NOVELS_ROOT_DIR.iterdir()
        if d.is_dir() and (d / "01_Raw_Text").exists()
    ]


def signal_handler(sig, frame, stop_event):
    console.print(
        "\n[bold red][!] Interrupted by user (Ctrl+C). Stopping safely...[/bold red]"
    )
    stop_event.set()


def run_cli():
    parser = argparse.ArgumentParser(
        description="NixOS AI: Headless Novel Processing Pipeline"
    )
    parser.add_argument(
        "novel_name", nargs="?", help="The exact folder name of the novel to process."
    )
    parser.add_argument(
        "--ch",
        type=int,
        default=1,
        help="The chapter number to start from (default: 1).",
    )
    parser.add_argument(
        "--list", action="store_true", help="List all available novels."
    )
    parser.add_argument(
        "--redo-pinyin",
        action="store_true",
        help="Regenerate Pinyin, EPUBs, and Anki decks without re-running AI.",
    )
    parser.add_argument(
        "--backend",
        choices=list(BACKENDS.keys()),
        default="Ollama",
        help=f"LLM backend to use (default: Ollama).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name to use (e.g. 'qwen3.5:9b'). If omitted, uses the first available model.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all models available on the selected backend.",
    )

    args = parser.parse_args()

    # 0. Set Backend
    set_backend(args.backend)

    # 1. Handle --list-models
    if args.list_models:
        models, error = list_models()
        if error:
            console.print(f"[bold red]Error:[/bold red] {error}")
            sys.exit(1)
        console.print(f"\n[bold cyan]🤖 Models on {args.backend}:[/bold cyan]")
        for m in models:
            console.print(f"  - {m}")
        sys.exit(0)

    # 2. Handle --list novels
    available_novels = get_available_novels()
    if args.list:
        console.print("\n[bold cyan]📚 Available Novels:[/bold cyan]")
        for novel in available_novels:
            console.print(f"  - {novel}")
        sys.exit(0)

    # 3. Validate Novel Input
    if not args.novel_name:
        parser.print_help()
        sys.exit(1)

    if args.novel_name not in available_novels:
        console.print(
            f"[bold red]Error:[/bold red] Novel '{args.novel_name}' not found."
        )
        console.print(f"Run 'python cli.py --list' to see available options.")
        sys.exit(1)

    # 4. Resolve Model
    if args.model:
        set_llm_model(args.model)
    else:
        # Auto-select first available model
        models, error = list_models()
        if error or not models:
            console.print(
                f"[bold red]Error:[/bold red] Could not fetch models from {args.backend}: {error}"
            )
            console.print("Use --model to specify one manually.")
            sys.exit(1)
        set_llm_model(models[0])
        console.print(f"[dim]Auto-selected model: {models[0]}[/dim]")

    # 5. Setup Safe Termination (Ctrl+C)
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, stop_event))

    # 6. Run Pipeline
    novel_dir = NOVELS_ROOT_DIR / args.novel_name
    console.print(
        f"\n[bold green]🚀 STARTING PIPELINE: {args.novel_name} (Starting at Ch {args.ch})[/bold green]"
    )
    console.print(
        f"[dim]Backend: {args.backend} | Model: {args.model or models[0]}[/dim]"
    )
    console.print("[dim]Press Ctrl+C at any time to safely pause and exit.[/dim]\n")

    try:
        process_novel(novel_dir, args.ch, stop_event, redo_pinyin=args.redo_pinyin)
    except Exception as e:
        console.print(f"[bold red]CRITICAL ERROR:[/bold red] {e}")


if __name__ == "__main__":
    run_cli()
