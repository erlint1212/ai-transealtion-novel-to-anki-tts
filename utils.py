import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pypinyin import Style, pinyin

from config import get_backend, get_llm_model


@dataclass
class Chapter:
    novel_name: str
    file_name: str
    content: str
    chapter_number: Optional[int] = None


def extract_chapter_number(file_name: str) -> Optional[int]:
    try:
        return int(file_name.split(".")[0].split("_")[1])
    except:
        return None


def chunk_text_into_numbered_lines(text: str, max_chars=400) -> List[Dict[int, str]]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks, current_chunk = [], {}
    current_length, line_idx = 0, 1
    for line in raw_lines:
        if current_length + len(line) > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk, current_length, line_idx = {}, 0, 1
        current_chunk[line_idx] = line
        current_length += len(line)
        line_idx += 1
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def get_relevant_glossary(text: str, master_glossary: dict) -> dict:
    """
    Scans the master glossary and returns a mini-glossary
    containing only the entities found in the current text chunk.
    """
    relevant = {"characters": {}, "places": {}, "items": {}, "skills": {}}
    categories = ["characters", "places", "items", "skills"]
    for category in categories:
        if category in master_glossary:
            for cn_name, data in master_glossary[category].items():
                if cn_name in text:
                    relevant[category][cn_name] = data
    return relevant


# LLM BACKEND FUNCTIONS

def list_models() -> Tuple[List[str], str]:
    """
    Queries the active backend for available models.
    Returns: (model_names, error_message)
      - On success: (["model1", "model2", ...], "")
      - On failure: ([], "error description")
    """
    backend = get_backend()

    if backend["type"] == "ollama":
        try:
            import ollama
            response = ollama.list()
            names = sorted(m.model for m in response.models)
            if not names:
                return [], "No models pulled. Run: ollama pull <model>"
            return names, ""
        except Exception as e:
            return [], f"Ollama not reachable: {e}"

    elif backend["type"] == "openai":
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url=backend["base_url"],
                api_key=backend["api_key"],
            )
            response = client.models.list()
            names = sorted(m.id for m in response.data)
            if not names:
                return [], "No models loaded in LM Studio. Load one in the app first."
            return names, ""
        except Exception as e:
            return [], f"LM Studio not reachable at {backend['base_url']}: {e}"

    return [], f"Unknown backend type: {backend['type']}"


def strip_thinking(text: str) -> str:
    """
    Strips chain-of-thought / reasoning artifacts from LLM output.
    Handles Qwen3.5 <think> blocks and leaked markdown reasoning headers.
    """
    # 1. Remove <think>...</think> blocks (Qwen3.5 thinking mode)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    # 2. Remove leaked reasoning lines like **Analyze the Request:**
    text = re.sub(
        r"^\*\*(?:Analyze|Drafting|Review|Refining|Process|Final|Translation)[^*]*\*\*:?\s*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # 3. Collapse multiple blank lines into one
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def call_llm(system_prompt: str, user_text: str) -> str:
    """Routes the LLM call to the active backend (Ollama or LM Studio)."""
    backend = get_backend()
    model = get_llm_model()

    if backend["type"] == "ollama":
        import ollama
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        raw = response["message"]["content"].strip()
        return strip_thinking(raw)

    elif backend["type"] == "openai":
        from openai import OpenAI
        client = OpenAI(base_url=backend["base_url"], api_key=backend["api_key"])
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
        )
        raw = response.choices[0].message.content.strip()
        return strip_thinking(raw)

    else:
        raise ValueError(f"Unknown backend type: {backend['type']}")


def unload_llm():
    """Frees VRAM by unloading the LLM from the active backend."""
    backend = get_backend()

    if backend["type"] == "ollama":
        import ollama
        model = get_llm_model()
        print("[SYSTEM] Unloading LLM from Ollama to free VRAM...")
        ollama.generate(model=model, prompt="", keep_alive=0)

    elif backend["type"] == "openai":
        import urllib.error
        import urllib.request

        model = get_llm_model()
        base = backend["base_url"].replace("/v1", "")  # http://localhost:1234
        url = f"{base}/api/v1/models/unload"

        print(f"[SYSTEM] Unloading '{model}' from LM Studio...")
        payload = json.dumps({"instance_id": model}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[SYSTEM] Model unloaded successfully.")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 404 and "not_found" in body:
                print(f"[SYSTEM] Model already unloaded. VRAM is free.")
            else:
                print(f"[SYSTEM] Warning: Unload returned {e.code}: {body}")
        except Exception as e:
            print(f"[SYSTEM] Warning: Could not unload model: {e}")


# TEXT PROCESSING UTILITIES

def parse_numbered_output(llm_output: str, expected_count: int) -> Dict[int, str]:
    results = {i: "" for i in range(1, expected_count + 1)}
    pattern = re.compile(r"^(\d+)[\.\:]\s*(.*)")
    for line in llm_output.splitlines():
        match = pattern.match(line.strip())
        if match:
            idx = int(match.group(1))
            if 1 <= idx <= expected_count:
                results[idx] = match.group(2).strip()
    return results


MAX_RETRIES = 2
MIN_FILL_RATIO = 0.5  # At least 50% of lines must be non-empty


def robust_parse(
    system_prompt: str,
    user_text: str,
    expected_count: int,
    label: str = "LLM",
) -> Dict[int, str]:
    """
    Calls the LLM, parses numbered output, and retries if too many lines
    came back empty (indicating the model dumped reasoning instead of output).
    """
    for attempt in range(1, MAX_RETRIES + 2):  # 1 initial + MAX_RETRIES
        raw = call_llm(system_prompt, user_text)
        results = parse_numbered_output(raw, expected_count)

        filled = sum(1 for v in results.values() if v)
        if filled >= expected_count * MIN_FILL_RATIO:
            return results

        print(
            f"      [{label}] Attempt {attempt}: Only {filled}/{expected_count} lines parsed. "
            f"{'Retrying...' if attempt <= MAX_RETRIES else 'Using partial result.'}"
        )

    return results


def clean_for_tts(text: str) -> str:
    """Sanitizes text to prevent TTS hallucinations on short/mixed-language lines."""
    text = re.sub(r"^(?i)(chapter|ch\.?)\s*\d+\s*[-—:]?\s*", "", text)
    text = re.sub(r"[""（）《》【】\-—]", "", text)
    text = re.sub(r"？+", "？", text)
    text = re.sub(r"！+", "！", text)
    text = re.sub(r"…+", "…", text)
    text = re.sub(r"\.+", ".", text)
    return text.strip()


def sanitize_filename(text: str) -> str:
    safe_text = text.replace(" ", "_")
    safe_text = re.sub(r'[<>:"/\\|?*]', "", safe_text)
    return safe_text


def generate_pinyin(text: str) -> str:
    pinyin_list = pinyin(text, style=Style.TONE, heteronym=False)
    return " ".join([item[0] for item in pinyin_list])
