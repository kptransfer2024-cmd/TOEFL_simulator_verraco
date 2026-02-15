from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from importers.text_cleaner import (
    clean_passage_lines,
    repair_misparsed_first_question,
)

PASSAGE_HEADER_RE = re.compile(r"(?m)^\s*Passage\s+(\d{1,3})\s*[-–—]\s*(.+?)\s*$")
Q_START_RE = re.compile(r"(?m)^\s*(\d{1,2})\.\s+")
OPT_RE = re.compile(r"(?m)^\s*([ABCD])\.\s+")


@dataclass
class ImportResult:
    passages: List[Dict[str, Any]]
    warnings: List[str]


def _split_passage_blocks(text: str) -> List[Dict[str, str]]:
    matches = list(PASSAGE_HEADER_RE.finditer(text))
    blocks: List[Dict[str, str]] = []
    if not matches:
        return blocks

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pid_num = int(m.group(1))
        pid = f"{pid_num:02d}"
        title = (m.group(2) or "").strip()
        body = text[start:end]
        blocks.append({"pid": pid, "title": title, "body": body})
    return blocks


def _parse_questions_from_body(body: str) -> (str, List[Dict[str, Any]]):
    """
    Returns (passage_text, questions).
    This parser assumes questions follow the passage.
    If no questions detected, everything is treated as passage text.
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n").strip()

    q_matches = list(Q_START_RE.finditer(body))
    if not q_matches:
        passage_text = clean_passage_lines(body.split("\n"))
        return passage_text, []

    first_q_pos = q_matches[0].start()
    passage_part = body[:first_q_pos].strip("\n")
    questions_part = body[first_q_pos:].strip("\n")

    passage_text = clean_passage_lines(passage_part.split("\n"))

    questions: List[Dict[str, Any]] = []
    q_spans = []
    for i, qm in enumerate(q_matches):
        start = qm.start()
        end = q_matches[i + 1].start() if i + 1 < len(q_matches) else len(questions_part) + first_q_pos
        q_spans.append((start, end))

    for (start, end) in q_spans:
        chunk = body[start:end].strip()
        mnum = Q_START_RE.match(chunk)
        if not mnum:
            continue
        qnum = int(mnum.group(1))
        chunk_rest = chunk[mnum.end():].strip()

        opt_matches = list(OPT_RE.finditer(chunk_rest))
        if len(opt_matches) < 2:
            stem = chunk_rest.strip()
            questions.append(
                {
                    "id": f"{qnum}",
                    "stem": stem,
                    "choices": ["", "", "", ""],
                    "correct_index": 0,
                    "explanation": None,
                }
            )
            continue

        stem = chunk_rest[:opt_matches[0].start()].strip()
        choices = ["", "", "", ""]
        for i_opt, om in enumerate(opt_matches):
            label = om.group(1).strip().upper()
            start_c = om.end()
            end_c = opt_matches[i_opt + 1].start() if i_opt + 1 < len(opt_matches) else len(chunk_rest)
            text_c = chunk_rest[start_c:end_c].strip()
            idx = {"A": 0, "B": 1, "C": 2, "D": 3}.get(label)
            if idx is not None:
                choices[idx] = text_c

        questions.append(
            {
                "id": f"{qnum}",
                "stem": stem,
                "choices": choices,
                "correct_index": 0,
                "explanation": None,
            }
        )

    return passage_text, questions


def import_passages_from_text(text: str) -> ImportResult:
    warnings: List[str] = []
    passages_out: List[Dict[str, Any]] = []

    blocks = _split_passage_blocks(text)
    if not blocks:
        return ImportResult(passages=[], warnings=["No passage headers found."])

    for b in blocks:
        pid = b["pid"]
        title = b["title"]
        body = b["body"]

        content, questions = _parse_questions_from_body(body)

        passage = {
            "id": pid,
            "title": title,
            "content": content,
            "questions": questions,
        }

        passage = repair_misparsed_first_question(passage)

        passages_out.append(passage)

    return ImportResult(passages=passages_out, warnings=warnings)
