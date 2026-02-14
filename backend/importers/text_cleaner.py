from __future__ import annotations

import re
from typing import Iterable, List

_RE_SPACES = re.compile(r"[ \t]+")
_RE_MULTI_BLANK = re.compile(r"\n{3,}")
_RE_CJK = re.compile(r"[\u4e00-\u9fff]")

# Detect the first real passage page and drop everything before it (removes TOC section).
_RE_REAL_PASSAGE01 = re.compile(r"^\s*Passage\s+0*1\s*-\s+", re.IGNORECASE)

# TOC-like lines: "Passage 33 - Title ............ 163"
_RE_TOC_PASSAGE_LINE = re.compile(r"^\s*Passage\s+\d{1,2}\s*-\s*.+?\.{6,}\s*\d+\s*$", re.IGNORECASE)

# Common watermarks / footer noise seen in this PDF.
_NOISE_SUBSTRINGS = (
    "cliffsnotes",
    "you get more than toefl",
    "q+a",
    "dcy",
    "微信公众号",
)

# Patterns for noise-only lines.
_NOISE_PATTERNS = [
    re.compile(r"cliffsnotes\.com", re.IGNORECASE),
    re.compile(r"^\s*q\+a\s*$", re.IGNORECASE),
    re.compile(r"^<PARSED TEXT FOR PAGE:", re.IGNORECASE),
    re.compile(r"^https?://\S+", re.IGNORECASE),
    re.compile(r"^\s*\d{1,4}\s*/\s*\d{1,4}\s*$"),          # 205/281
    re.compile(r"^\s*\d{1,4}\s*$"),                        # page number alone
    re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2},\s*\d{1,2}:\d{2}\s*(AM|PM)\s*$", re.IGNORECASE),
    re.compile(r"^\s*appendex[::]?\s*keys\s*$", re.IGNORECASE),
]

def normalize_line(line: str) -> str:
    s = line.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u00ad", "")  # soft hyphen
    s = s.strip()
    s = _RE_SPACES.sub(" ", s)
    return s

def is_noise_line(line: str) -> bool:
    if not line:
        return False

    low = line.lower()
    for sub in _NOISE_SUBSTRINGS:
        if sub in low:
            return True

    if _RE_TOC_PASSAGE_LINE.match(line):
        return True

    return any(p.search(line) for p in _NOISE_PATTERNS)

def clean_lines(lines: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    for raw in lines:
        s = normalize_line(raw)
        if not s:
            normalized.append("")
            continue
        if is_noise_line(s):
            continue
        # This PDF's Chinese lines are not part of the test content (mostly TOC/watermarks).
        if _RE_CJK.search(s):
            continue
        normalized.append(s)

    # Drop everything before the first real passage to remove TOC (Passage 33-50 listing).
    start_idx = 0
    for i, ln in enumerate(normalized):
        if _RE_REAL_PASSAGE01.match(ln):
            start_idx = i
            break

    return normalized[start_idx:]

def join_paragraphs(lines: List[str]) -> str:
    text = "\n".join(lines)
    text = _RE_MULTI_BLANK.sub("\n\n", text)
    return text.strip()
