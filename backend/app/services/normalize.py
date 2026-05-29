"""Request normalization per TR-1.01-11."""

import unicodedata
from app.models.schemas import ALLOWED_LANGUAGES


def normalize_text(text: str | None) -> str | None:
    """NFKC, line endings, trim. Returns None if empty after trim."""
    if text is None:
        return None
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.strip()
    return s if s else None


def normalize_language(lang: str | None) -> str | None:
    """Trim, canonical BCP-47 casing, return None if empty. Must be in allowed set."""
    if lang is None or not lang.strip():
        return None
    s = to_canonical_bcp47(lang.strip())
    return s if s in ALLOWED_LANGUAGES else None


def to_canonical_bcp47(lang: str) -> str:
    """Normalize to canonical BCP-47 (e.g. zh-hant -> zh-Hant)."""
    if not lang or not lang.strip():
        return ""
    parts = lang.strip().split("-")
    if len(parts) == 1:
        return parts[0].lower()
    result = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) and p[0].isalpha():
            result.append(p[0].upper() + p[1:].lower() if len(p) > 1 else p.upper())
        else:
            result.append(p)
    return "-".join(result)
