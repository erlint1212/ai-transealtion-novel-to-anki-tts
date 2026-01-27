import argparse
import sys
import threading
import signal
from pathlib import Path

# Local Imports
from config import NOVELS_ROOT_DIR, console
from main import process_novel

def get_available_novels():
    """Returns a list of valid novel directories."""
    if not NOVELS_ROOT_DIR.exists():
        return []
    return [d.name for d in NOVELS_ROOT_DIR.iterdir() if d.is_dir() and (d / "01_Raw_Text").exists()]

def signal_handler(sig, frame, stop_event):
    """Handles Ctrl+C to safely terminate the pipeline."""
    console.print("\n[bold red][!] Interrupted by user (Ctrl+C). Stopping safely...[/bold red]")
    stop_event.set()

def run_cli():
    parser = argparse.ArgumentParser(description="NixOS AI: Headless Novel Processing Pipeline")
    parser.add_argument("novel_name", nargs="?", help="The exact folder name of the novel to process.")
    parser.add_argument("--ch", type=int, default=1, help="The chapter number to start from (default: 1).")
    parser.add_argument("--list", action="store_true", help="List all available novels.")
    parser.add_argument("--redo-pinyin", action="store_true", help="Regenerate Pinyin, EPUBs, and Anki decks without re-running AI.")

    args = parser.parse_args()

    # 1. Handle --list argument
    available_novels = get_available_novels()
    if args.list:
        console.print("\n[bold cyan]📚 Available Novels:[/bold cyan]")
        for novel in available_novels:
            console.print(f"  - {novel}")
        sys.exit(0)

    # 2. Validate Novel Input
    if not args.novel_name:
        parser.print_help()
        sys.exit(1)

    if args.novel_name not in available_novels:
        console.print(f"[bold red]Error:[/bold red] Novel '{args.novel_name}' not found.")
        console.print(f"Run 'python cli.py --list' to see available options.")
        sys.exit(1)

    # 3. Setup Safe Termination (Ctrl+C)
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, stop_event))

    # 4. Run Pipeline
    novel_dir = NOVELS_ROOT_DIR / args.novel_name
    console.print(f"\n[bold green]🚀 STARTING PIPELINE: {args.novel_name} (Starting at Ch {args.ch})[/bold green]")
    console.print("[dim]Press Ctrl+C at any time to safely pause and exit.[/dim]\n")

    try:
        process_novel(novel_dir, args.ch, stop_event, redo_pinyin=args.redo_pinyin)
    except Exception as e:
        console.print(f"[bold red]CRITICAL ERROR:[/bold red] {e}")

if __name__ == "__main__":
    run_cli()
