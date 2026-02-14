from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class KeysParseResult:
    keys: Dict[str, List[str]]
    warnings: List[str]


_RE_KEYS_ANCHOR = re.compile(r"\bkeys\b", re.IGNORECASE)
_RE_KEYS_ANCHOR_CN = re.compile(r"appendix[:：]?\s*keys", re.IGNORECASE)

_RE_PASSAGE_ROW_1 = re.compile(r"^\s*Passage\s+(\d{1,2})\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
_RE_PASSAGE_ROW_2 = re.compile(r"^\s*(\d{1,2})\s*[:\-]\s*(.+?)\s*$")

# Examples handled:
# - "1.B 2.D 3.A 4.C ..."
# - "1) B 2) D ..."
_RE_QA_PAIR = re.compile(r"(\d{1,2})\s*[\.\)\:]?\s*([A-D])", re.IGNORECASE)

_RE_LETTERS = re.compile(r"[A-D]", re.IGNORECASE)


def _normalize_pid(n: int) -> str:
    return f"{n:02d}"


def _extract_letters_from_tail(tail: str) -> List[str]:
    # Prefer structured (question number + letter) if present; otherwise fall back to raw letters.
    pairs = _RE_QA_PAIR.findall(tail)
    if pairs:
        # Sort by question number to keep order stable
        pairs_sorted = sorted(((int(qn), ans.upper()) for qn, ans in pairs), key=lambda x: x[0])
        return [ans for _, ans in pairs_sorted]
    return [m.group(0).upper() for m in _RE_LETTERS.finditer(tail)]


def parse_keys_from_lines(lines: List[str]) -> KeysParseResult:
    warnings: List[str] = []
    keys: Dict[str, List[str]] = {}

    anchor_idx: Optional[int] = None
    for i, ln in enumerate(lines):
        if _RE_KEYS_ANCHOR.search(ln) or _RE_KEYS_ANCHOR_CN.search(ln):
            anchor_idx = i
            break

    if anchor_idx is None:
        warnings.append("Keys anchor not found.")
        return KeysParseResult(keys=keys, warnings=warnings)

    # Scan after the anchor. We do not assume any fixed table structure.
    # We attempt to detect passage-numbered rows.
    for ln in lines[anchor_idx + 1 :]:
        ln = ln.strip()
        if not ln:
            continue

        m1 = _RE_PASSAGE_ROW_1.match(ln)
        if m1:
            pid = _normalize_pid(int(m1.group(1)))
            tail = m1.group(2)
            letters = _extract_letters_from_tail(tail)
            if letters:
                keys[pid] = letters
            continue

        m2 = _RE_PASSAGE_ROW_2.match(ln)
        if m2:
            pid = _normalize_pid(int(m2.group(1)))
            tail = m2.group(2)
            letters = _extract_letters_from_tail(tail)
            if letters:
                keys[pid] = letters
            continue

    if not keys:
        warnings.append("No usable key rows found after Keys anchor.")

    return KeysParseResult(keys=keys, warnings=warnings)
