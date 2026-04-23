"""
Copyright (c) 2026 Richard G and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Chunking helpers for graph build ingestion.

Modes:
- fixed: deterministic char/sentence-aware split
- semantic: LLM-guided boundary selection per block
- hybrid: fixed first, LLM split only for complex blocks
- llama_index: LlamaIndex semantic splitter with embedding model
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.core.config import Config
from app.core.llm.factory import create_openai_provider
from app.core.llm.providers.openai.provider import OpenAIProvider
from app.core.utils.text_processor import split_text_into_chunks

CHUNK_MODE_FIXED = "fixed"
CHUNK_MODE_SEMANTIC = "semantic"
CHUNK_MODE_HYBRID = "hybrid"
CHUNK_MODE_LLAMA_INDEX = "llama_index"
SUPPORTED_CHUNK_MODES = {
    CHUNK_MODE_FIXED,
    CHUNK_MODE_SEMANTIC,
    CHUNK_MODE_HYBRID,
    CHUNK_MODE_LLAMA_INDEX,
}

_PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n{2,}")
_MIN_CHUNK_SIZE = 80
_MAX_BLOCK_SIZE_MULTIPLIER = 4
_MIN_BLOCK_SIZE = 2000
_MAX_BLOCK_SIZE = 12000
_LLAMA_INDEX_INSTRUMENTED = False


def normalize_chunk_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_CHUNK_MODES:
        return normalized
    return CHUNK_MODE_FIXED


@dataclass
class ChunkingContext:
    text: str
    chunk_size: int
    overlap: int
    llm_provider: OpenAIProvider | None = None


class ChunkingStrategy(ABC):
    @abstractmethod
    def split(self, context: ChunkingContext) -> list[str]:
        raise NotImplementedError


class FixedChunkingStrategy(ChunkingStrategy):
    def split(self, context: ChunkingContext) -> list[str]:
        return split_text_into_chunks(context.text, context.chunk_size, context.overlap)


class SemanticChunkingStrategy(ChunkingStrategy):
    def __init__(self, *, use_llm_for_all_blocks: bool):
        self.use_llm_for_all_blocks = use_llm_for_all_blocks

    def split(self, context: ChunkingContext) -> list[str]:
        blocks = _split_into_blocks(context.text, context.chunk_size)
        if not blocks:
            return []

        provider = context.llm_provider or _build_default_llm_provider()
        chunks: list[str] = []
        for block in blocks:
            use_llm = self.use_llm_for_all_blocks or _block_needs_llm(block, context.chunk_size)
            if use_llm:
                llm_chunks = _split_block_with_llm(
                    provider,
                    block,
                    chunk_size=context.chunk_size,
                    overlap=context.overlap,
                )
                if llm_chunks:
                    chunks.extend(llm_chunks)
                    continue
            chunks.extend(split_text_into_chunks(block, context.chunk_size, context.overlap))

        return _normalize_chunks_with_overlap(chunks, context.overlap)


class LlamaIndexChunkingStrategy(ChunkingStrategy):
    """
    Semantic chunking by LlamaIndex.

    Required instrumentation:
    from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
    LlamaIndexInstrumentor().instrument()
    """

    def split(self, context: ChunkingContext) -> list[str]:
        normalized_text = str(context.text or "").strip()
        if not normalized_text:
            return []
        try:
            _ensure_llama_index_instrumented()
            from llama_index.core import Document
            from llama_index.core.node_parser import SemanticSplitterNodeParser
            from llama_index.embeddings.openai import OpenAIEmbedding

            embedding_model = (
                Config.GRAPHITI_DEFAULT_EMBEDDING_MODEL
                if str(Config.GRAPHITI_DEFAULT_EMBEDDING_MODEL or "").strip()
                else "text-embedding-3-large"
            )
            embed_model = OpenAIEmbedding(
                model=embedding_model,
                api_key=Config.OPENAI_API_KEY or Config.LLM_API_KEY,
                api_base=Config.OPENAI_BASE_URL or Config.LLM_BASE_URL,
            )
            splitter = SemanticSplitterNodeParser(
                embed_model=embed_model,
            )
            nodes = splitter.get_nodes_from_documents([Document(text=normalized_text)])
            chunks = []
            for node in nodes:
                content = getattr(node, "text", None)
                if content is None and hasattr(node, "get_content"):
                    content = node.get_content()
                normalized = str(content or "").strip()
                if normalized:
                    chunks.append(normalized)
            if not chunks:
                return split_text_into_chunks(normalized_text, context.chunk_size, context.overlap)
            return _normalize_chunks_with_overlap(chunks, context.overlap)
        except Exception:
            # Keep build resilient when LlamaIndex splitter fails.
            return split_text_into_chunks(normalized_text, context.chunk_size, context.overlap)


def split_text_with_mode(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    *,
    chunk_mode: str = CHUNK_MODE_FIXED,
    llm_provider: OpenAIProvider | None = None,
) -> list[str]:
    normalized_mode = normalize_chunk_mode(chunk_mode)
    context = ChunkingContext(
        text=str(text or ""),
        chunk_size=max(int(chunk_size or 500), _MIN_CHUNK_SIZE),
        overlap=0,
        llm_provider=llm_provider,
    )
    context.overlap = max(0, min(int(overlap or 0), context.chunk_size - 1))
    strategy = _resolve_chunking_strategy(normalized_mode)
    return strategy.split(context)


def _resolve_chunking_strategy(chunk_mode: str) -> ChunkingStrategy:
    normalized_mode = normalize_chunk_mode(chunk_mode)
    if normalized_mode == CHUNK_MODE_SEMANTIC:
        return SemanticChunkingStrategy(use_llm_for_all_blocks=True)
    if normalized_mode == CHUNK_MODE_HYBRID:
        return SemanticChunkingStrategy(use_llm_for_all_blocks=False)
    if normalized_mode == CHUNK_MODE_LLAMA_INDEX:
        return LlamaIndexChunkingStrategy()
    return FixedChunkingStrategy()


def _ensure_llama_index_instrumented() -> None:
    global _LLAMA_INDEX_INSTRUMENTED
    if _LLAMA_INDEX_INSTRUMENTED:
        return
    from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

    LlamaIndexInstrumentor().instrument()
    _LLAMA_INDEX_INSTRUMENTED = True


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


def _normalize_chunks_with_overlap(chunks: list[str], overlap: int) -> list[str]:
    cleaned_chunks = [chunk.strip() for chunk in chunks if str(chunk or "").strip()]
    if overlap <= 0 or len(cleaned_chunks) <= 1:
        return cleaned_chunks
    return _apply_overlap(cleaned_chunks, overlap)


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
