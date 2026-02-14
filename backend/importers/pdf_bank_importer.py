from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


_RE_PASSAGE_HEADER = re.compile(r"(?m)^\s*Passage\s+(\d+)\s*-\s*(.+?)\s*$")

# Matches question numbers like: "1." possibly followed by unusual invisible chars
_RE_Q_START = re.compile(r"(?m)^\s*(\d{1,2})\.\s*")

# Matches choice lines like: "A. ..." "B. ..."
_RE_CHOICE = re.compile(r"(?m)^\s*([A-D])\.\s*(.*)$")

_LETTERS = ("A", "B", "C", "D")
_LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}

# Common invisible/formatting characters that break regex matching
_INVISIBLE_CHARS = [
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\ufeff",  # BOM
    "\u00ad",  # soft hyphen
    "\u2060",  # word joiner
]


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _squash_newlines(text: str) -> str:
    return re.sub(r"\s*\n\s*", " ", text).strip()


class PDFBankParser:
    """
    Produces passages.json with schema compatible with services/exam_services.py:

    {
      "passages": [
        {
          "id": "01",
          "title": "...",
          "content": "...",
          "questions": [
            {"id": "01-1", "stem": "...", "choices": ["...","...","...","..."], "correct_index": 0}
          ]
        }
      ]
    }
    """

    def parse(self, raw_text: str) -> List[Dict[str, Any]]:
        text = _clean_text(raw_text)
        headers = list(_RE_PASSAGE_HEADER.finditer(text))
        if not headers:
            return []

        passages: List[Dict[str, Any]] = []

        for i, h in enumerate(headers):
            pid_raw = h.group(1).strip()
            title = h.group(2).strip()
            pid = pid_raw.zfill(2)

            start = h.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
            block = text[start:end].strip()

            content, questions = self._split_and_parse_block(pid, block)

            passages.append(
                {
                    "id": pid,
                    "title": title,
                    "content": content,
                    "questions": questions,
                }
            )

        return passages

    def _split_and_parse_block(self, pid: str, block: str) -> Tuple[str, List[Dict[str, Any]]]:
        q1 = _RE_Q_START.search(block)
        if not q1:
            return block.strip(), []

        content = block[: q1.start()].strip()
        q_block = block[q1.start():].strip()

        questions = self._parse_questions(pid, q_block)
        return content, questions

    def _parse_questions(self, pid: str, q_block: str) -> List[Dict[str, Any]]:
        starts = list(_RE_Q_START.finditer(q_block))
        out: List[Dict[str, Any]] = []

        for i, m in enumerate(starts):
            qnum = int(m.group(1))
            s = m.end()
            e = starts[i + 1].start() if i + 1 < len(starts) else len(q_block)
            chunk = q_block[s:e].strip()

            stem, choices = self._parse_stem_and_choices(chunk)

            out.append(
                {
                    "id": f"{pid}-{qnum}",
                    "stem": stem,
                    "choices": choices,
                    "correct_index": 0,
                    "explanation": None,
                }
            )

        return out

    def _parse_stem_and_choices(self, chunk: str) -> Tuple[str, List[str]]:
        choice_matches = list(_RE_CHOICE.finditer(chunk))

        # No recognizable A-D options found
        if not choice_matches:
            stem = _squash_newlines(chunk)
            return stem, ["", "", "", ""]

        stem = _squash_newlines(chunk[: choice_matches[0].start()].strip())

        choices_map: Dict[str, str] = {}
        for j, c in enumerate(choice_matches):
            letter = c.group(1).strip().upper()

            # Capture the rest of the line after "A."
            first_line = (c.group(2) or "").strip()

            # Include possible wrapped lines until next choice or end
            start = c.end()
            end = choice_matches[j + 1].start() if j + 1 < len(choice_matches) else len(chunk)
            continuation = chunk[start:end].strip()

            full = (first_line + "\n" + continuation).strip()
            choices_map[letter] = _squash_newlines(full)

        choices = [choices_map.get(L, "") for L in _LETTERS]
        return stem, choices
