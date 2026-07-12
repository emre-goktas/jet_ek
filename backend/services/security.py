"""
Shared security/sanitization helpers used across pdf_service, ai_service and routers.
"""
import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(name: str, max_chars: int = 150, max_bytes: int = 210) -> str:
    """Cleans a user- or AI-supplied name so it is safe to use as a filesystem path component.

    Strips control characters, path separators and traversal sequences, then
    caps length by both character count and UTF-8 byte count (some downstream
    systems have byte-oriented filename limits).
    """
    clean = _CONTROL_CHARS_RE.sub(" ", name)
    clean = clean.replace("/", "-").replace("\\", "-").replace(":", "-")
    clean = clean.replace("..", "-")
    clean = clean.strip(" .")

    if len(clean) > max_chars:
        clean = clean[:max_chars].strip(" .")

    encoded = clean.encode("utf-8")
    if len(encoded) > max_bytes:
        clean = encoded[:max_bytes].decode("utf-8", "ignore").strip(" .")

    return clean or "evrak"
