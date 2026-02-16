from __future__ import annotations

import re
from typing import Dict, List, Optional


# ----------------------------
# Base regex for Q1-9 (do not change)
# ----------------------------
Q_START_RE = re.compile(r"(?m)^\s*(\d+)\.\s+")
OPT_AD_RE = re.compile(r"(?m)^\s*([ABCD])\.\s+")
ANSWER_CHOICES_RE = re.compile(r"(?im)^\s*Answer\s+Choices\s*$")

# Q10 only
OPT_AF_LINE_RE = re.compile(r"^\s*([A-F])\.\s+(.*)$")
BULLET_ONLY_RE = re.compile(r"^\s*[·●]\s*$")


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _split_questions(passage_text: str) -> List[str]:
    # Split by question starts like "1. ", "2. ", ...
    starts = list(Q_START_RE.finditer(passage_text))
    if not starts:
        return []
    blocks: List[str] = []
    for i, m in enumerate(starts):
        a = m.start()
        b = starts[i + 1].start() if i + 1 < len(starts) else len(passage_text)
        blocks.append(passage_text[a:b].strip())
    return blocks


def _parse_q10_summary(block: str) -> Optional[Dict]:
    """
    Parse TOEFL Reading Q10 summary:
    - Intro sentence (summary lead)
    - Answer Choices A-F
    - Select exactly 3
    Returns dict or None if not parseable as Q10.
    """
    if not ANSWER_CHOICES_RE.search(block):
        return None

    lines = [ln.rstrip() for ln in block.splitlines()]

    # Locate "Answer Choices"
    ac_idx = None
    for i, ln in enumerate(lines):
        if ANSWER_CHOICES_RE.match(ln.strip()):
            ac_idx = i
            break
    if ac_idx is None:
        return None

    before = lines[:ac_idx]
    after = lines[ac_idx + 1 :]

    # Extract prompt + intro from "before"
    # Heuristic: last non-empty, non-bullet line is intro, all non-empty lines become prompt text.
    prompt_lines: List[str] = []
    intro = ""
    for ln in before:
        t = ln.strip()
        if not t:
            continue
        if BULLET_ONLY_RE.match(t):
            continue
        prompt_lines.append(t)
        intro = t

    prompt = _collapse_spaces(" ".join(prompt_lines))
    intro = _collapse_spaces(intro)

    # Parse A-F choices from "after"
    choices: List[Dict[str, str]] = []
    cur_id: Optional[str] = None
    cur_buf: List[str] = []

    def flush() -> None:
        nonlocal cur_id, cur_buf
        if cur_id and cur_buf:
            choices.append({"id": cur_id, "text": _collapse_spaces(" ".join(cur_buf))})
        cur_id = None
        cur_buf = []

    for ln in after:
        if not ln.strip():
            continue
        m = OPT_AF_LINE_RE.match(ln)
        if m:
            flush()
            cur_id = m.group(1)
            cur_buf = [m.group(2).strip()]
        else:
            if cur_id:
                cur_buf.append(ln.strip())

    flush()

    # Must be A-F (6 choices) to be treated as Q10
    if len(choices) != 6:
        return None

    return {
        "type": "summary",
        "prompt": prompt,
        "intro": intro,
        "max_selections": 3,
        "choices": choices,
    }


def parse_question_block(block: str) -> Dict:
    """
    Parse a question block.
    For Q1-9: original A-D single choice
    For Q10: summary A-F with max 3 selections
    """
    m = Q_START_RE.match(block)
    if not m:
        raise ValueError("Invalid question block: missing number header")

    number = int(m.group(1))
    body = block[m.end() :].strip()

    # Q10 branch (strict)
    if number == 10:
        q10 = _parse_q10_summary(block)
        if q10 is None:
            # Fall back to legacy parsing if not really Q10
            pass
        else:
            return {"number": number, **q10}

    # Legacy Q1-9 parsing (A-D)
    # Strategy:
    # - Split body into prompt text + options A-D
    opts = list(OPT_AD_RE.finditer(body))
    if not opts:
        # Some questions might be "insert sentence" etc; keep as text-only
        return {"number": number, "type": "text", "prompt": _collapse_spaces(body)}

    prompt_text = body[: opts[0].start()].strip()
    prompt_text = _collapse_spaces(prompt_text)

    choices: List[Dict[str, str]] = []
    for i, om in enumerate(opts):
        cid = om.group(1)
        a = om.end()
        b = opts[i + 1].start() if i + 1 < len(opts) else len(body)
        ctext = _collapse_spaces(body[a:b])
        choices.append({"id": cid, "text": ctext})

    return {
        "number": number,
        "type": "single",
        "prompt": prompt_text,
        "choices": choices,
    }


def parse_passage_questions(passage_text: str) -> List[Dict]:
    blocks = _split_questions(passage_text)
    questions: List[Dict] = []
    for blk in blocks:
        questions.append(parse_question_block(blk))
    return questions
