from __future__ import annotations

from typing import Any, Dict, List, Optional

_LETTERS = ["A", "B", "C", "D"]

def normalize_question(q: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a raw question dict from different sources into a stable schema for templates:
      - prompt: str
      - type: "single" / "multi"
      - choices: List[[letter, text]]
      - correct_index: int (single) or None
      - correct_indices: List[int] (multi) or None
      - correct_letter(s): str or List[str] (for review display)
    """
    qq = dict(q)

    # unify prompt field
    if "prompt" not in qq:
        if "stem" in qq:
            qq["prompt"] = qq.get("stem") or ""
        else:
            qq["prompt"] = qq.get("question") or ""

    # unify type field
    qtype = qq.get("type")
    if not qtype:
        # if your data has something like "multi" / "multiple", map it
        qtype = "single"
    if qtype not in ("single", "multi"):
        qtype = "single"
    qq["type"] = qtype

    # unify choices to pairs [letter, text]
    raw_choices = qq.get("choices") or []
    choices_pairs: List[List[str]] = []

    # Case 1: already [["A","text"], ...]
    if raw_choices and isinstance(raw_choices[0], (list, tuple)) and len(raw_choices[0]) >= 2:
        for item in raw_choices:
            letter = str(item[0]).strip()
            text = str(item[1]).strip()
            choices_pairs.append([letter, text])
    else:
        # Case 2: ["text", ...] -> assign letters
        for i, text in enumerate(raw_choices):
            letter = _LETTERS[i] if i < len(_LETTERS) else str(i)
            choices_pairs.append([letter, str(text).strip()])

    qq["choices"] = choices_pairs

    # unify correct answers
    # single:
    ci = qq.get("correct_index", None)
    # multi:
    cis = qq.get("correct_indices", None)

    if cis is not None:
        # multi indices -> letters
        if not isinstance(cis, list):
            cis = [cis]
        cis_int = []
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
            correct_letter = str(qq["correct_letter"]).strip()

        qq["correct_letter"] = correct_letter
        qq["correct_letters"] = None
        qq["correct_indices"] = None

    return qq
