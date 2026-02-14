from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.store import ATTEMPTS
from core import store
from services.shuffle_service import shuffle_exam_set


@dataclass(frozen=True)
class BankLoadResult:
    exam_set: Dict[str, Any]
    warnings: List[str]


_LETTERS = ("A", "B", "C", "D")
_LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}
_INDEX_TO_LETTER = {0: "A", 1: "B", 2: "C", 3: "D"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_passages_path() -> Path:
    return _project_root() / "data" / "passages.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _pick_first_key(d: Dict[str, Any], keys: Tuple[str, ...]) -> Tuple[str, Any]:
    for k in keys:
        if k in d:
            return k, d.get(k)
    return "", None


def _normalize_choices(raw_choices: Any, warnings: List[str], qid: str) -> List[str]:
    """
    Supported forms:
      - ["choice1", "choice2", "choice3", "choice4"]
      - [{"label":"A","text":"..."}, ...]
      - [("A","..."), ...]
    Always returns a list of 4 strings (may include empty strings if data is missing).
    """
    out = ["", "", "", ""]
    if isinstance(raw_choices, list) and len(raw_choices) == 4:
        if all(isinstance(x, str) for x in raw_choices):
            return [_as_str(x) for x in raw_choices]

        if all(isinstance(x, dict) for x in raw_choices):
            for item in raw_choices:
                label = _as_str(item.get("label")).upper()
                text = _as_str(item.get("text"))
                if label in _LETTER_TO_INDEX:
                    out[_LETTER_TO_INDEX[label]] = text
            if any(out):
                return out

        if all(isinstance(x, (list, tuple)) and len(x) == 2 for x in raw_choices):
            for label, text in raw_choices:
                lab = _as_str(label).upper()
                if lab in _LETTER_TO_INDEX:
                    out[_LETTER_TO_INDEX[lab]] = _as_str(text)
            if any(out):
                return out

    warnings.append(f"{qid}: choices format not recognized; filled with blanks.")
    return out


def _normalize_correct_index(q: Dict[str, Any], warnings: List[str], qid: str) -> Optional[int]:
    """
    Supported forms:
      - correct_index: int in [0..3]
      - correct: ["A"] or ["B"] etc.
      - correct: "A"
    Returns int or None.
    """
    ci = q.get("correct_index")
    if isinstance(ci, int) and 0 <= ci <= 3:
        return ci

    corr = q.get("correct")
    if isinstance(corr, list) and corr:
        letter = _as_str(corr[0]).upper()
        if letter in _LETTER_TO_INDEX:
            return _LETTER_TO_INDEX[letter]
    if isinstance(corr, str):
        letter = _as_str(corr).upper()
        if letter in _LETTER_TO_INDEX:
            return _LETTER_TO_INDEX[letter]

    warnings.append(f"{qid}: missing/invalid correct answer; defaulted to A.")
    return 0


def _normalize_passage_schema(p: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
    """
    Input passage might be:
      - {"id","title","content","questions":[{"id","stem","choices","correct_index"}]}
      - {"id","title","text","questions":[{"number","prompt","choices":[{"label","text"}],"correct":["A"]}]}
      - {"id","title","passage","questions":[...]}
    Output passage schema (internal normalized):
      - {"id","title","content","questions":[{"id","stem","choices","correct_index","explanation"}]}
    """
    pid = _as_str(p.get("id"))
    title = _as_str(p.get("title"))

    _, content_val = _pick_first_key(p, ("content", "text", "passage"))
    content = _as_str(content_val)

    qs_raw = p.get("questions")
    if not isinstance(qs_raw, list):
        warnings.append(f"passage {pid or 'unknown'}: questions missing or not a list; replaced with empty list.")
        qs_raw = []

    qs_norm: List[Dict[str, Any]] = []
    for idx, q in enumerate(qs_raw):
        if not isinstance(q, dict):
            warnings.append(f"passage {pid or 'unknown'}: question[{idx}] not an object; skipped.")
            continue

        qid = _as_str(q.get("id"))
        if not qid:
            num = q.get("number")
            if isinstance(num, int):
                qid = f"{pid}-{num}" if pid else str(num)
            else:
                qid = f"{pid}-q{idx+1}" if pid else f"q{idx+1}"

        _, stem_val = _pick_first_key(q, ("stem", "prompt"))
        stem = _as_str(stem_val)

        raw_choices = q.get("choices")
        choices = _normalize_choices(raw_choices, warnings, qid)

        ci = _normalize_correct_index(q, warnings, qid)
        explanation = q.get("explanation")

        qs_norm.append(
            {
                "id": qid,
                "stem": stem,
                "choices": choices,
                "correct_index": int(ci) if ci is not None else 0,
                "explanation": explanation,
            }
        )

    return {
        "id": pid,
        "title": title,
        "content": content,
        "questions": qs_norm,
    }


def _validate_passages_payload_loose(payload: Any) -> Tuple[bool, List[str]]:
    """
    Loose validation: require a dict with a 'passages' list.
    Normalize downstream; do not fail hard on alternative schemas.
    """
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["Root must be an object."]
    passages = payload.get("passages")
    if not isinstance(passages, list):
        return False, ["'passages' must be a list."]
    if not passages:
        errors.append("'passages' is empty.")
    return len(errors) == 0, errors


def _passage_to_exam_set(p_norm: Dict[str, Any]) -> Dict[str, Any]:
    pid = _as_str(p_norm.get("id"))
    title = _as_str(p_norm.get("title"))
    passage_text = _as_str(p_norm.get("content"))

    questions_out: List[Dict[str, Any]] = []
    for q in p_norm.get("questions", []):
        qid = _as_str(q.get("id"))
        stem = _as_str(q.get("stem"))
        raw_choices = q.get("choices", ["", "", "", ""])
        ci = q.get("correct_index", 0)
        correct_letter = _INDEX_TO_LETTER.get(int(ci) if isinstance(ci, int) else 0, "A")

        choices: List[Tuple[str, str]] = [(_LETTERS[i], _as_str(raw_choices[i])) for i in range(4)]

        questions_out.append(
            {
                "id": qid,
                "type": "single",
                "prompt": stem,
                "choices": choices,
                "correct": [correct_letter],
                "explanation": q.get("explanation"),
            }
        )

    label = f"Reading Passage {pid}" if pid else "Reading Passage"
    if title:
        label = f"{label}: {title}"

    return {
        "id": f"reading-{pid}" if pid else "reading",
        "title": label,
        "passage": passage_text,
        "questions": questions_out,
    }


def _load_exam_set_from_passages(
    passages_path: Optional[str | Path],
    passage_index: int,
) -> BankLoadResult:
    path = Path(passages_path) if passages_path else _default_passages_path()
    path = path.expanduser().resolve()

    warnings: List[str] = []

    if not path.exists():
        raise FileNotFoundError(f"passages.json not found: {path}")

    payload = _read_json(path)
    ok, errors = _validate_passages_payload_loose(payload)
    if not ok:
        raise ValueError("Invalid passages.json payload:\n" + "\n".join(errors))

    passages_raw: List[Dict[str, Any]] = payload.get("passages", [])
    if not passages_raw:
        raise ValueError("passages.json contains zero passages.")

    idx = passage_index % len(passages_raw)
    if idx != passage_index:
        warnings.append("passage_index out of range; wrapped by modulo.")

    p_norm = _normalize_passage_schema(passages_raw[idx], warnings)
    exam_set = _passage_to_exam_set(p_norm)

    if not exam_set["questions"]:
        warnings.append("Selected passage has zero questions after normalization.")

    return BankLoadResult(exam_set=exam_set, warnings=warnings)


def _derive_passage_index(seed: int, passages_count: int) -> int:
    rng = random.Random(seed)
    return rng.randrange(passages_count)


def _count_passages(passages_path: Optional[str | Path]) -> int:
    path = Path(passages_path) if passages_path else _default_passages_path()
    path = path.expanduser().resolve()
    payload = _read_json(path)
    passages = payload.get("passages")
    if isinstance(passages, list) and passages:
        return len(passages)
    return 1


def pick_exam_set() -> dict:
    """
    Returns an exam_set compatible with templates, shuffle_service, and grader.
    Uses passage_index=0 as a simple default.
    """
    res = _load_exam_set_from_passages(None, passage_index=0)
    return res.exam_set


def pick_exam_set_for_attempt(seed: int) -> dict:
    """
    Deterministic passage selection for an attempt based on the seed.
    """
    count = _count_passages(None)
    passage_index = _derive_passage_index(seed, passages_count=count)
    res = _load_exam_set_from_passages(None, passage_index=passage_index)
    return res.exam_set


def create_attempt(minutes: int) -> str:
    store.ATTEMPT_COUNTER += 1
    attempt_id = str(store.ATTEMPT_COUNTER)

    seed = random.randint(1, 10**9)
    exam_set = pick_exam_set_for_attempt(seed)

    ATTEMPTS[attempt_id] = {
        "minutes": int(minutes),
        "started_at": int(time.time()),
        "submitted": False,
        "timed_out": False,
        "result": None,
        "raw_exam_set": exam_set,
        "shuffle_seed": seed,
        "passage_seed": seed,
    }
    return attempt_id


def get_attempt(attempt_id: str) -> dict | None:
    return ATTEMPTS.get(attempt_id)


def get_exam_set_for_attempt(attempt: dict) -> dict:
    cached = attempt.get("shuffled_exam_set")
    if cached is not None:
        return cached

    raw = attempt.get("raw_exam_set")
    if raw is None:
        seed = int(attempt.get("passage_seed") or attempt.get("shuffle_seed") or 1)
        raw = pick_exam_set_for_attempt(seed)
        attempt["raw_exam_set"] = raw

    shuffled = shuffle_exam_set(raw, seed=int(attempt.get("shuffle_seed") or 1))
    attempt["shuffled_exam_set"] = shuffled
    return shuffled


def duration_seconds(attempt: dict) -> int:
    return int(attempt["minutes"]) * 60
