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

def create_epub_audio_item(audio_filepath: str, filename: str) -> epub.EpubItem:
    """Creates an EPUB audio item from a local file."""
    with open(audio_filepath, 'rb') as f:
        audio_content = f.read()
    return epub.EpubItem(
        uid=f"audio_{filename}", 
        file_name=f"media/{filename}", 
        media_type="audio/wav", 
        content=audio_content
    )

def create_epub_chapter(title: str, file_name: str, body_html: str, stylesheet: epub.EpubItem) -> epub.EpubHtml:
    ch = epub.EpubHtml(title=title, file_name=f"{file_name}.xhtml", lang='en')
    ch.content = f"<html><head><link rel='stylesheet' href='style/nav.css' type='text/css'/></head><body>{body_html}</body></html>"
    ch.add_item(stylesheet)
    return ch
