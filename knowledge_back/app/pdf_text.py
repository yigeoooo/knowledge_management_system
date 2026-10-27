"""Normalize PDF font-map artifacts without changing code or mathematical notation."""

import re
import unicodedata

_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")
_IDEOGRAPHS = re.compile(r"[\u2f00-\u2fd5\uf900-\ufaff\U0002f800-\U0002fa1f]")


def is_pdf_source(source):
    return str(source.get("filename") or "").lower().endswith(".pdf")


def normalize_pdf_text(text):
    # PDF font maps sometimes use control characters for word separators.
    # Preserve those boundaries and real line breaks; dropping them joins words.
    text = _CONTROLS.sub(" ", text.replace("\x0c", "\n\n"))
    # Full NFKC would change formulas (x² -> x2), full-width characters and code.
    # Only fold the alternate CJK glyphs emitted by PDF font mappings.
    return _IDEOGRAPHS.sub(lambda match: unicodedata.normalize("NFKC", match[0]), text)


def readable_source(source):
    result = dict(source)
    if is_pdf_source(result):
        for field in ("content", "heading_path"):
            if isinstance(result.get(field), str):
                result[field] = normalize_pdf_text(result[field])
    return result


def readable_answer(answer, sources):
    if isinstance(answer, str) and any(is_pdf_source(source) for source in sources):
        return normalize_pdf_text(answer)
    return answer
