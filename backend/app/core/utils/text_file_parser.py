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
"""

from pathlib import Path


def _read_text_with_fallback(file_path: str) -> str:
    data = Path(file_path).read_bytes()

    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    
    # use charset_normalizer to detect encoding
    encoding = None
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        pass
    
    if not encoding:
        try:
            import chardet
            result = chardet.detect(data)
            encoding = result.get('encoding') if result else None
        except Exception:
            pass
    
    if not encoding:
        encoding = 'utf-8'
    
    return data.decode(encoding, errors='replace')


class FileParser:
    SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown', '.txt'}
    
    @classmethod
    def extract_text(
        cls,
        file_path: str,
        *,
        pdf_page_from: int | None = None,
        pdf_page_to: int | None = None,
    ) -> str:
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")
        
        suffix = path.suffix.lower()
        
        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"unsupported file format: {suffix}")
        
        if suffix == '.pdf':
            return cls._extract_from_pdf(
                file_path,
                page_from=pdf_page_from,
                page_to=pdf_page_to,
            )
        elif suffix in {'.md', '.markdown'}:
            return cls._extract_from_md(file_path)
        elif suffix == '.txt':
            return cls._extract_from_txt(file_path)
        
        raise ValueError(f"Unsupported file format: {suffix}")
    
    @staticmethod
    def _extract_from_pdf(
        file_path: str,
        *,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> str:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("missingPyMuPDF: pip install PyMuPDF")
        
        text_parts = []
        with fitz.open(file_path) as doc:
            total_pages = len(doc)
            if total_pages <= 0:
                return ""
            if page_from is None and page_to is None:
                start_index = 0
                end_index = total_pages - 1
            else:
                normalized_from = max(1, int(page_from or 1))
                normalized_to = max(1, int(page_to or total_pages))
                if normalized_from > normalized_to:
                    normalized_from, normalized_to = normalized_to, normalized_from
                start_index = max(0, normalized_from - 1)
                end_index = min(total_pages - 1, normalized_to - 1)
            if start_index > end_index:
                return ""
            for page_index in range(start_index, end_index + 1):
                page = doc[page_index]
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        return _read_text_with_fallback(file_path)
    
    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        return _read_text_with_fallback(file_path)
    
    @classmethod
    def extract_from_multiple(cls, file_paths: list[str]) -> str:
        all_texts = []
        
        for i, file_path in enumerate(file_paths, 1):
            try:
                text = cls.extract_text(file_path)
                filename = Path(file_path).name
                all_texts.append(f"=== File {i}: {filename} ===\n{text}")
            except Exception as e:
                all_texts.append(f"=== File {i}: {file_path} (extract failed: {str(e)}) ===")
        
        return "\n\n".join(all_texts)
