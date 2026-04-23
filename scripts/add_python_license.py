#!/usr/bin/env python3
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

One-off: prepend MIT license to all project Python files (idempotent).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LICENSE_INNER = """Copyright (c) 2026 Richard G and contributors

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
SOFTWARE."""

MARKER = "Copyright (c) 2026 Richard G and contributors"


def module_opens_with_richard_license(text: str) -> bool:
    """True only if the first module docstring (after shebang/encoding) includes the marker."""
    _, body = split_shebang_and_encoding(text)
    raw = body
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    j = 0
    while j < len(raw) and raw[j] in "\n\r \t":
        j += 1
    if j + 3 > len(raw) or raw[j : j + 3] != '"""':
        return False
    end = find_triple_double_end(raw, j)
    if end == -1:
        return False
    inner = raw[j + 3 : end - 3]
    return MARKER in inner


def wrap_docstring(inner: str) -> str:
    return f'"""\n{inner}\n"""'


def find_triple_double_end(text: str, start: int) -> int:
    """Return index after closing \"\"\" if text[start:start+3] is \"\"\"; else -1."""
    if text[start : start + 3] != '"""':
        return -1
    pos = start + 3
    while True:
        idx = text.find('"""', pos)
        if idx == -1:
            return -1
        return idx + 3


def split_shebang_and_encoding(text: str) -> tuple[str, str]:
    """Return (prefix_lines_including_newlines, rest)."""
    lines = text.splitlines(keepends=True)
    i = 0
    prefix: list[str] = []
    if lines and lines[0].startswith("#!"):
        prefix.append(lines[0])
        i = 1
    if i < len(lines) and "coding" in lines[i] and lines[i].lstrip().startswith("#"):
        prefix.append(lines[i])
        i += 1
    rest = "".join(lines[i:])
    return "".join(prefix), rest


def apply_license(content: str) -> str | None:
    if module_opens_with_richard_license(content):
        return None

    prefix, body = split_shebang_and_encoding(content)
    raw = body
    bom = ""
    if raw.startswith("\ufeff"):
        bom = "\ufeff"
        raw = raw[1:]

    j = 0
    while j < len(raw) and raw[j] in "\n\r \t":
        j += 1

    if j + 3 <= len(raw) and raw[j : j + 3] == '"""':
        end = find_triple_double_end(raw, j)
        if end == -1:
            return None
        inner = raw[j + 3 : end - 3]
        tail = raw[end:].lstrip("\n")
        merged = wrap_docstring(f"{LICENSE_INNER}\n\n{inner.strip()}")
        new_body = bom + merged + ("\n\n" if tail else "\n") + tail
        return prefix + new_body

    new_body = bom + wrap_docstring(LICENSE_INNER) + "\n\n" + raw[j:]
    return prefix + new_body


def main() -> int:
    paths = sorted(ROOT.rglob("*.py"))
    changed = 0
    for path in paths:
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        new_text = apply_license(text)
        if new_text is not None and new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="\n")
            changed += 1
            print(path.relative_to(ROOT))
    print(f"Updated {changed} file(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
