from __future__ import annotations

from typing import Any, Dict, List, Optional

_LETTERS = ["A", "B", "C", "D"]


def _norm_type(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in {"single", "radio", "one"}:
        return "single"
    if s in {"multi", "multiple", "multiple_answer", "checkbox"}:
        return "multi"
    if s in {"summary", "q10", "prose_summary"}:
        return "summary"
    return "single"


def normalize_question(q: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a raw question dict from different sources into a stable schema for templates:
      - prompt: str
      - type: "single" / "multi" / "summary"
      - intro: Optional[str] (used by summary)
      - choices: List[[letter, text]]
      - correct_index: int (single) or None
      - correct_indices: List[int] (multi/summary) or None
      - correct_letter(s): str or List[str] (for review display)
    """
    qq = dict(q)

    # ----------------------------
    # unify prompt field
    # ----------------------------
    if "prompt" not in qq or qq.get("prompt") is None:
        if "stem" in qq:
            qq["prompt"] = qq.get("stem") or ""
        else:
            qq["prompt"] = qq.get("question") or ""

    # intro is used by summary questions (Q10)
    if "intro" in qq and qq.get("intro") is None:
        qq["intro"] = ""

    # ----------------------------
    # unify type field
    # ----------------------------
    qtype = _norm_type(qq.get("type") or qq.get("question_type") or qq.get("qtype"))
    qq["type"] = qtype

    # ----------------------------
    # unify choices to pairs [letter, text]
    # supports:
    #   - [["A","text"], ...]
    #   - ["text", ...]
    #   - [{"id":"A","text":"..."}, ...]  (Q10)
    # ----------------------------
    raw_choices = qq.get("choices") or qq.get("options") or []
    choices_pairs: List[List[str]] = []

    if raw_choices and isinstance(raw_choices, list):
        first = raw_choices[0]

        # Case 1: already [["A","text"], ...]
        if isinstance(first, (list, tuple)) and len(first) >= 2:
            for item in raw_choices:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                letter = str(item[0]).strip().upper()
                text = str(item[1]).strip()
                if letter and text:
                    choices_pairs.append([letter, text])

        # Case 2: [{"id":"A","text":"..."}, ...]
        elif isinstance(first, dict):
            for i, item in enumerate(raw_choices):
                if not isinstance(item, dict):
                    continue
                letter = str(item.get("id") or item.get("label") or "").strip().upper()
                text = str(item.get("text") or item.get("value") or item.get("choice") or "").strip()
                if not letter:
                    # fallback: assign letters by index if missing
                    letter = _LETTERS[i] if i < len(_LETTERS) else str(i + 1)
                if text:
                    choices_pairs.append([letter, text])

        # Case 3: ["text", ...] -> assign letters
        else:
            for i, text in enumerate(raw_choices):
                letter = _LETTERS[i] if i < len(_LETTERS) else str(i + 1)
                choices_pairs.append([letter, str(text).strip()])

    qq["choices"] = choices_pairs

    # ----------------------------
    # unify correct answers
    # keep your existing behavior:
    #   - if correct_indices exists => multi path
    #   - else => single path
    # summary (Q10) may still omit grading for now; we keep fields compatible.
    # ----------------------------
    ci = qq.get("correct_index", None)
    cis = qq.get("correct_indices", None)

    if cis is not None:
        # multi indices -> letters
        if not isinstance(cis, list):
            cis = [cis]
        cis_int: List[int] = []
        for x in cis:
            try:
                cis_int.append(int(x))
            except Exception:
                pass
        qq["correct_indices"] = cis_int
        qq["correct_letters"] = [_LETTERS[i] for i in cis_int if 0 <= i < len(_LETTERS)]
        qq["correct_index"] = None
        qq["correct_letter"] = None

    else:
        # single index -> letter
        correct_letter: Optional[str] = None
        try:
            if ci is not None:
                ci_int = int(ci)
                qq["correct_index"] = ci_int
                if 0 <= ci_int < len(_LETTERS):
                    correct_letter = _LETTERS[ci_int]
        except Exception:
            qq["correct_index"] = None

        # If some upstream already stored correct_letter, keep it
        if qq.get("correct_letter"):
            correct_letter = str(qq["correct_letter"]).strip().upper()

        qq["correct_letter"] = correct_letter
        qq["correct_letters"] = None
        qq["correct_indices"] = None

    return qq


from services.q10_repo import get_q10_question


def append_q10_questions(questions: list, passage_no: int) -> list:
    """
    Append Q10 (summary) to an existing question list.
    Keeps existing 1-9 intact.
    """
    q10 = get_q10_question(passage_no)
    if not q10:
        return questions

    # light safety: ensure type is summary so exam.html uses checkbox branch
    if isinstance(q10, dict):
        t = _norm_type(q10.get("type"))
        if t != "summary":
            q10 = dict(q10)
            q10["type"] = "summary"

    questions.append(q10)
    return questions
