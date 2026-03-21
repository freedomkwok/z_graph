"""
Text processing helpers.
"""

import re
from typing import List

from app.core.utils.text_file_parser import FileParser


def split_text_into_chunks(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks: List[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            for sep in ["。", "！", "？", ".\n", "!\n", "?\n", "\n\n", ". ", "! ", "? "]:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else len(text)

    return chunks


class TextProcessor:
    @staticmethod
    def extract_from_files(file_paths: List[str]) -> str:
        return FileParser.extract_from_multiple(file_paths)

    @staticmethod
    def split_text(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> List[str]:
        return split_text_into_chunks(text, chunk_size, overlap)

    @staticmethod
    def preprocess_text(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    @staticmethod
    def get_text_stats(text: str) -> dict:
        return {
            "total_chars": len(text),
            "total_lines": text.count("\n") + 1,
            "total_words": len(text.split()),
        }
