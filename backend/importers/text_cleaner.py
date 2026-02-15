from __future__ import annotations

import re
from typing import List

_RE_SPACES = re.compile(r"[ \t]+")
_RE_MULTI_BLANK = re.compile(r"\n{3,}")

_PASSAGE_PREFIX_RE = re.compile(r"(?i)^\s*Passage\s+\d{1,3}\s*[-–—]\s*")
_PARAGRAPH_TAG_RE = re.compile(r"\[\s*Paragraph\s*\d+\s*\]|\u3010\s*Paragraph\s*\d+\s*\u3011", re.IGNORECASE)

_NOISE_LINE_RES = [
    re.compile(r"cliffsnotes\.com", re.IGNORECASE),
    re.compile(r"copyright\s+©", re.IGNORECASE),
]


def _normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _RE_SPACES.sub(" ", s)
    s = _RE_MULTI_BLANK.sub("\n\n", s)
    return s.strip()


def _is_noise_line(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    return any(rx.search(t) for rx in _NOISE_LINE_RES)


def extract_title_from_header_line(line: str) -> str:
    """
    Input:  "Passage 02 - Alaska and Bark Beetles"
    Output: "Alaska and Bark Beetles"
    """
    t = (line or "").strip()
    t = _PASSAGE_PREFIX_RE.sub("", t)
    return t.strip()


def clean_passage_lines(lines: List[str], *, drop_noise_lines: bool = True) -> str:
    """
    Key rule: never drop the first paragraph by slicing.
    Only apply light cleanup: whitespace, optional noise lines, and paragraph tags.
    """
    out: List[str] = []
    for raw in lines:
        if raw is None:
            continue
        line = str(raw).rstrip("\n")

        if drop_noise_lines and _is_noise_line(line):
            continue

        line = _PARAGRAPH_TAG_RE.sub("", line)
        out.append(line)

    return _normalize_text("\n".join(out))


def repair_misparsed_first_question(passage: dict) -> dict:
    """
    Fix a common parse failure:
    - First "question" has 4 empty choices
    - First "stem" is very long (likely actual passage text)
    Merge that stem back into content and drop the fake question.
    """
    qs = passage.get("questions")
    if not isinstance(qs, list) or not qs:
        return passage

    q0 = qs[0]
    if not isinstance(q0, dict):
        return passage

    choices = q0.get("choices")
    stem = (q0.get("stem") or "").strip()

    if (
        isinstance(choices, list)
        and len(choices) == 4
        and all(((c or "").strip() == "") for c in choices)
        and len(stem) >= 200
    ):
        content = (passage.get("content") or "").strip()
        passage["content"] = (content + "\n" + stem).strip() if content else stem
        passage["questions"] = qs[1:]

    return passage
