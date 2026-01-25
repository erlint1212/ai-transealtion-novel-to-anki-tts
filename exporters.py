from pathlib import Path
from ebooklib import epub
import os

def get_epub_css() -> epub.EpubItem:
    return epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content="""
        .study-block { margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid #eee; }
        .cn { font-size: 1.4em; font-weight: bold; margin: 0; color: #000; }
        .py { font-size: 1em; color: #555; margin: 0; font-family: monospace; }
        .lit { font-size: 1em; font-style: italic; color: #666; margin: 0; }
        .en { font-size: 1.1em; font-weight: bold; color: #1a1a1a; margin: 0; }
        h1 { text-align: center; margin-bottom: 30px; font-size: 2em; }
        audio { width: 100%; height: 35px; margin-top: 10px; }
    """)

def create_epub_audio_item(audio_filepath: Path, filename: str) -> epub.EpubItem:
    """Loads a WAV file from the disk into the EPUB manifest."""
    with open(audio_filepath, 'rb') as f:
        audio_content = f.read()
    return epub.EpubItem(
        uid=f"audio_{filename}", 
        file_name=f"media/{filename}", 
        media_type="audio/wav", 
        content=audio_content
    )

def build_final_epub(novel_name: str, novel_dir: Path):
    """Compiles individual .xhtml chapters and .wav media into the final .epub."""
    book = epub.EpubBook()
    book.set_title(novel_name)
    book.set_language('en')

    epub_css = get_epub_css()
    book.add_item(epub_css)

    epub_dir = novel_dir / "03_EPUB_Chapters"
    media_dir = novel_dir / "media"
    
    book_chapters = []
    
    # 1. Load and stitch all the XHTML Chapters in order
    for xhtml_file in sorted(epub_dir.glob("*.xhtml")):
        content = xhtml_file.read_text(encoding='utf-8')
        
        # Extract the English chapter title from the <h1> tag
        title_match = content.split("<h1>")[1].split("</h1>")[0] if "<h1>" in content else xhtml_file.stem

        ch = epub.EpubHtml(title=title_match, file_name=xhtml_file.name, lang='en')
        ch.content = content
        ch.add_item(epub_css)
        book.add_item(ch)
        book_chapters.append(ch)

    # 2. Embed all audio files into the EPUB container
    for audio_file in media_dir.glob("*.wav"):
        audio_item = create_epub_audio_item(audio_file, audio_file.name)
        book.add_item(audio_item)

    # 3. Finalize Book Structure
    book.toc = book_chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + book_chapters
    
    epub.write_epub(str(novel_dir / f"{novel_name}.epub"), book)
