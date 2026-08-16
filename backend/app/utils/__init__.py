"""Pure helper utilities: artist normalization, slugs, duration parsing."""
import re
import unicodedata
from typing import Optional

# ---------------------------------------------------------------------------
# Artist normalization
# ---------------------------------------------------------------------------

_PUNCT_SPLIT_RE = re.compile(r"[\s;,.]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_LEADING_THE_RE = re.compile(r"^(?:the|the\s+)")


def normalize_artist_name(name: str) -> str:
    """Normalize an artist display name to a canonical comparison key.

    The goal is that common punctuation/spacing variants of the same logical
    artist compare equal while the original display name is preserved by the
    caller::

        A.R. Rahman   -> a r rahman
        A.R Rahman    -> a r rahman
        A.R.Rahman    -> a r rahman
        A R Rahman    -> a r rahman

    The function only collapses punctuation/spacing/case — it never merges
    distinct people based on fuzzy similarity.
    """
    if not name:
        return ""
    # NFC unicode normalization: é -> e + combining accent, then strip accents
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = _PUNCT_SPLIT_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def artist_slug(name: str) -> str:
    """Build a URL-safe slug from an artist display name.

    ``A.R. Rahman`` -> ``a-r-rahman``. This matches the typical artist URL
    pattern (``/artist/a-r-rahman``) used by index pages.
    """
    text = normalize_artist_name(name)
    if not text:
        return ""
    slug = re.sub(r"\s+", "-", text)
    # Trim leading/trailing hyphens and collapse duplicates
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def split_artist_names(raw: str) -> list[str]:
    """Split a combined artist field into individual display names.

    Handles separators commonly found on audio sites: ``;``, ``,``,
    ``feat.``/``ft.``, ``&``/``and``. Returns cleaned display names.
    """
    if not raw:
        return []
    parts = re.split(r";|,|&|\band\b|\bfeat(?:uring)?\.?|\bft\.?", raw)
    names = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" -–—()[]")
        if name and name.lower() not in ("unknown", "n/a", "na"):
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Duration parsing / formatting
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")
_MINS_SECS_RE = re.compile(
    r"^\s*(?:(\d{1,4})\s*(?:minutes?|mins|min|m)\s*)?"
    r"(?:(\d{1,3})\s*(?:seconds?|secs|sec|s))?\s*$",
    re.IGNORECASE,
)
_PLAIN_SECONDS_RE = re.compile(r"^\d+$")


def parse_duration_seconds(raw) -> Optional[int]:
    """Parse a duration string into total seconds.

    Supports ``MM:SS``, ``HH:MM:SS``, ``H:MM:SS``, ``Xm Ys``, ``Ns`` and plain
    seconds. Returns ``None`` when the value cannot be parsed (never raises).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0, int(raw))

    text = str(raw).strip().replace(" ", "")
    if not text:
        return None

    match = _DURATION_RE.match(text)
    if match:
        h, m, s = match.groups()
        h = int(h) if h else 0
        m = int(m)
        s = int(s)
        return h * 3600 + m * 60 + s

    match = _MINS_SECS_RE.match(str(raw).strip())
    if match:
        mins, secs = match.groups()
        if mins or secs:
            return int(mins or 0) * 60 + int(secs or 0)

    if _PLAIN_SECONDS_RE.match(text):
        return int(text)

    return None


def format_duration_seconds(seconds: Optional[int]) -> str:
    """Format seconds as ``MM:SS`` (or ``HH:MM:SS`` when >= 1 hour).

    Returns ``--:--`` when the duration is unknown.
    """
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
