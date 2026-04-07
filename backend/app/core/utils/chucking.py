"""
Chunking helpers for graph build ingestion.

Modes:
- fixed: deterministic char/sentence-aware split
- semantic: LLM-guided boundary selection per block
- hybrid: fixed first, LLM split only for complex blocks
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import Config
from app.core.llm.factory import create_openai_provider
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.utils.text_processor import split_text_into_chunks

CHUNK_MODE_FIXED = "fixed"
CHUNK_MODE_SEMANTIC = "semantic"
CHUNK_MODE_HYBRID = "hybrid"
SUPPORTED_CHUNK_MODES = {CHUNK_MODE_FIXED, CHUNK_MODE_SEMANTIC, CHUNK_MODE_HYBRID}

_PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n{2,}")
_MIN_CHUNK_SIZE = 80
_MAX_BLOCK_SIZE_MULTIPLIER = 4
_MIN_BLOCK_SIZE = 2000
_MAX_BLOCK_SIZE = 12000


def normalize_chunk_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_CHUNK_MODES:
        return normalized
    return CHUNK_MODE_FIXED


def split_text_with_mode(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    *,
    chunk_mode: str = CHUNK_MODE_FIXED,
    llm_provider: OpenAIProvider | None = None,
) -> list[str]:
    normalized_mode = normalize_chunk_mode(chunk_mode)
    normalized_chunk_size = max(int(chunk_size or 500), _MIN_CHUNK_SIZE)
    normalized_overlap = max(0, min(int(overlap or 0), normalized_chunk_size - 1))

    if normalized_mode == CHUNK_MODE_FIXED:
        return split_text_into_chunks(text, normalized_chunk_size, normalized_overlap)

    blocks = _split_into_blocks(text, normalized_chunk_size)
    if not blocks:
        return []

    provider = llm_provider or _build_default_llm_provider()
    chunks: list[str] = []
    for block in blocks:
        use_llm = normalized_mode == CHUNK_MODE_SEMANTIC or _block_needs_llm(block, normalized_chunk_size)
        if use_llm:
            llm_chunks = _split_block_with_llm(
                provider,
                block,
                chunk_size=normalized_chunk_size,
                overlap=normalized_overlap,
            )
            if llm_chunks:
                chunks.extend(llm_chunks)
                continue
        chunks.extend(split_text_into_chunks(block, normalized_chunk_size, normalized_overlap))

    cleaned_chunks = [chunk.strip() for chunk in chunks if str(chunk or "").strip()]
    if normalized_overlap <= 0 or len(cleaned_chunks) <= 1:
        return cleaned_chunks
    return _apply_overlap(cleaned_chunks, normalized_overlap)


def _build_default_llm_provider() -> OpenAIProvider:
    return create_openai_provider(
        model=Config.LLM_MODEL_NAME,
        api_key=Config.LLM_API_KEY,
        base_url=Config.LLM_BASE_URL,
    )


def _split_into_blocks(text: str, chunk_size: int) -> list[str]:
    normalized_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized_text:
        return []

    raw_paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_PATTERN.split(normalized_text) if p.strip()]
    if not raw_paragraphs:
        return [normalized_text]

    block_limit = min(max(chunk_size * _MAX_BLOCK_SIZE_MULTIPLIER, _MIN_BLOCK_SIZE), _MAX_BLOCK_SIZE)
    blocks: list[str] = []
    current_parts: list[str] = []
    current_size = 0
    for paragraph in raw_paragraphs:
        paragraph_size = len(paragraph)
        if current_parts and current_size + paragraph_size + 2 > block_limit:
            blocks.append("\n\n".join(current_parts).strip())
            current_parts = [paragraph]
            current_size = paragraph_size
            continue
        current_parts.append(paragraph)
        current_size += paragraph_size + (2 if current_parts else 0)

    if current_parts:
        blocks.append("\n\n".join(current_parts).strip())
    return [block for block in blocks if block]


def _block_needs_llm(block: str, chunk_size: int) -> bool:
    block_len = len(block)
    if block_len > int(chunk_size * 1.4):
        return True
    paragraph_count = block.count("\n\n") + 1
    if paragraph_count >= 4 and block_len > int(chunk_size * 0.8):
        return True
    sentence_breaks = sum(block.count(sep) for sep in [". ", "。", "!", "！", "?", "？"])
    return sentence_breaks < 2 and block_len > int(chunk_size * 0.8)


def _split_block_with_llm(
    llm_provider: OpenAIProvider,
    block: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    system_prompt = (
        "You split text into coherent chunks for retrieval. "
        "Output strict JSON with key 'chunks' as a list of strings. "
        "Keep original wording exactly (no paraphrase), preserve order, and avoid dropping content."
    )
    user_prompt = (
        "Split the following text into coherent chunks.\n"
        f"Target chunk size: about {chunk_size} characters.\n"
        f"Maximum chunk size: {int(chunk_size * 1.15)} characters.\n"
        f"Desired contextual overlap between adjacent chunks: about {overlap} characters.\n"
        "Rules:\n"
        "1) Preserve original wording and sequence.\n"
        "2) Prefer splitting at headings/paragraph/sentence boundaries.\n"
        "3) Do not return empty chunks.\n"
        "4) Return JSON only: {\"chunks\": [\"...\", \"...\"]}\n\n"
        "TEXT:\n"
        f"{block}"
    )

    try:
        payload = llm_provider.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
            operation="Chunking_Semantic_Split",
            metadata={"component": "chunking", "mode": "semantic"},
        )
    except Exception:
        return []

    chunks = payload.get("chunks", []) if isinstance(payload, dict) else []
    if not isinstance(chunks, list):
        return []
    normalized_chunks = [str(item).strip() for item in chunks if str(item).strip()]
    if not normalized_chunks:
        return []
    if not _is_valid_llm_chunks(block, normalized_chunks):
        return []
    return normalized_chunks


def _is_valid_llm_chunks(source_text: str, chunks: list[str]) -> bool:
    cursor = 0
    for chunk in chunks:
        index = source_text.find(chunk, cursor)
        if index == -1:
            return False
        cursor = index + len(chunk)
    return True


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) < 2:
        return chunks

    result = [chunks[0]]
    for index in range(1, len(chunks)):
        previous = result[-1]
        current = chunks[index]
        prefix = previous[-overlap:] if len(previous) > overlap else previous
        if current.startswith(prefix):
            result.append(current)
            continue
        result.append(f"{prefix}{current}")
    return result
