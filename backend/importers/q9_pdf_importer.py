# backend/importers/q9_pdf_importer.py
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any

import pdfplumber

PASSAGE_RE = re.compile(r"(?m)^\s*Passage\s+(\d{1,3})\s*-\s*(.+?)\s*$")
PARA_RE = re.compile(r"(?m)^\s*【Paragraph\s+(\d+)】\s*")
Q9_RE = re.compile(r"(?m)^\s*9\.\s*Look\s+at\s+the\s+four\s+squares\b")
WHERE_FIT_RE = re.compile(r"(?i)where\s+would\s+the\s+sentence\s+best\s+fit")
# Capture marker blocks like [A] [B] [C] [D]
MARKERS_RE = re.compile(r"\[A\]|\[B\]|\[C\]|\[D\]")

def extract_text(pdf_path: Path) -> str:
    chunks = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            chunks.append(t)
    return "\n".join(chunks)

def split_passages(full_text: str) -> List[str]:
    # Split by "Passage XX - Title" headers
    matches = list(PASSAGE_RE.finditer(full_text))
    if not matches:
        return []
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        blocks.append(full_text[start:end].strip())
    return blocks

def parse_one_passage(block: str) -> Dict[str, Any]:
    m = PASSAGE_RE.search(block)
    if not m:
        raise ValueError("Passage header not found")

    pid = int(m.group(1))
    title = m.group(2).strip()

    # Extract paragraph label + paragraph text (we only need the paragraph that contains [A][B][C][D])
    # In your "clean Q9" PDF, usually it's a single paragraph excerpt.
    para_m = PARA_RE.search(block)
    para_label = None
    para_text = None
    if para_m:
        para_label = f"Paragraph {para_m.group(1)}"
        # paragraph starts at para_m.end and ends before "9."
        q9_m = Q9_RE.search(block)
        end = q9_m.start() if q9_m else len(block)
        para_text = block[para_m.end():end].strip()
    else:
        # fallback: try from after header to before Q9
        q9_m = Q9_RE.search(block)
        start = m.end()
        end = q9_m.start() if q9_m else len(block)
        para_text = block[start:end].strip()

    # Parse Q9: the inserted sentence is typically the line after the prompt and before "Where would..."
    q9_m = Q9_RE.search(block)
    if not q9_m:
        raise ValueError(f"Q9 not found in passage {pid}")

    q9_block = block[q9_m.start():]
    # Find the line that is the sentence to insert:
    # We take text between the prompt line and the "Where would..." line.
    # This is robust even if prompt spans multiple lines.
    where_m = WHERE_FIT_RE.search(q9_block)
    if not where_m:
        raise ValueError(f"'Where would...' not found in passage {pid}")

    # The sentence is usually right before the "Where would..." line.
    # We'll take the last non-empty line in the part before where_m.
    before_where = q9_block[:where_m.start()]
    lines = [ln.strip() for ln in before_where.splitlines() if ln.strip()]
    # Heuristic: the inserted sentence is the last line after the prompt
    sentence = lines[-1]

    # Validate markers exist in paragraph text
    markers = MARKERS_RE.findall(para_text or "")
    marker_set = set(markers)
    if marker_set != {"[A]", "[B]", "[C]", "[D]"}:
        # Keep it as warning; do not hard-fail here.
        marker_ok = False
    else:
        marker_ok = True

    qid = f"P{pid:02d}-Q09"
    question = {
        "id": qid,
        "question_type": "insert_sentence",
        "paragraph_label": para_label,
        "paragraph_text": para_text,
        "sentence": sentence,
        "prompt": "Look at the four squares [A], [B], [C], [D] that indicate where the following sentence could be added to the passage. Where would the sentence best fit?",
        "options": [
            {"label": "A", "text": "Insert at [A]"},
            {"label": "B", "text": "Insert at [B]"},
            {"label": "C", "text": "Insert at [C]"},
            {"label": "D", "text": "Insert at [D]"},
        ],
        "meta": {"markers_ok": marker_ok},
    }

    return {
        "passage_id": f"P{pid:02d}",
        "title": title,
        "questions": [question],
    }

def parse_q9_pdf(pdf_path: Path) -> Dict[str, Any]:
    text = extract_text(pdf_path)
    blocks = split_passages(text)
    passages = []
    warnings = []
    for b in blocks:
        try:
            p = parse_one_passage(b)
            if not p["questions"][0]["meta"]["markers_ok"]:
                warnings.append(f"{p['passage_id']}: missing/invalid [A][B][C][D] markers in paragraph_text")
            passages.append(p)
        except Exception as e:
            warnings.append(f"Failed to parse passage block: {e}")
    return {"passages": passages, "warnings": warnings}
