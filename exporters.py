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

def create_epub_audio_item(audio_filepath: Path, base_novel_dir: Path) -> epub.EpubItem:
    with open(audio_filepath, 'rb') as f:
        audio_content = f.read()
    
    rel_path = audio_filepath.relative_to(base_novel_dir)
    return epub.EpubItem(
        uid=f"audio_{audio_filepath.stem}", 
        file_name=str(rel_path.as_posix()), 
        media_type="audio/ogg", 
        content=audio_content
    )

def build_final_epub(novel_name: str, novel_dir: Path, metadata: dict):
    """Compiles the EPUB using standard text, audio, and custom metadata."""
    book = epub.EpubBook()

    # --- 1. APPLY METADATA ---
    book_title = metadata.get("title", novel_name)
    book.set_title(book_title)
    book.set_language(metadata.get("language", "en"))
    book.add_author(metadata.get("author", "Unknown Author"))
    
    description = metadata.get("description", "")
    if description:
        book.add_metadata('DC', 'description', description)

    # --- 2. APPLY COVER IMAGE ---
    cover_filename = metadata.get("cover_image", "")
    if cover_filename:
        cover_path = novel_dir / cover_filename
        if cover_path.exists():
            with open(cover_path, 'rb') as cover_file:
                book.set_cover("cover.jpg", cover_file.read())
        else:
            print(f"[Warning] Cover image '{cover_filename}' not found at {cover_path}.")

    # --- 3. BUILD BOOK STRUCTURE ---
    epub_css = get_epub_css()
    book.add_item(epub_css)

    epub_dir = novel_dir / "03_EPUB_Chapters"
    media_dir = novel_dir / "media"
    
    book_chapters = []
    
    # Load and stitch XHTML Chapters
    for xhtml_file in sorted(epub_dir.glob("*.xhtml")):
        content = xhtml_file.read_text(encoding='utf-8')
        title_match = content.split("<h1>")[1].split("</h1>")[0] if "<h1>" in content else xhtml_file.stem

        ch = epub.EpubHtml(title=title_match, file_name=xhtml_file.name, lang='en')
        ch.content = content
        ch.add_item(epub_css)
        book.add_item(ch)
        book_chapters.append(ch)

    # Embed audio files
    for audio_file in media_dir.rglob("*.opus"):
        audio_item = create_epub_audio_item(audio_file, novel_dir)
        book.add_item(audio_item)

    # Finalize Book
    book.toc = book_chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + book_chapters
    
    epub.write_epub(str(novel_dir / f"{book_title}.epub"), book)
