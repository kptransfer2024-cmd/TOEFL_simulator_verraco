from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


JsonPath = Union[str, Path]


@dataclass(frozen=True)
class BankLoadResult:
    exam_set: Dict[str, Any]
    warnings: List[str]


# ----------------------------
# Paths
# ----------------------------

def _project_root() -> Path:
    # backend/services -> backend
    return Path(__file__).resolve().parents[1]


def _data_dir() -> Path:
    return _project_root() / "data"


def _default_passages_path() -> Path:
    return _data_dir() / "passages.json"


def _default_q9_path() -> Path:
    return _data_dir() / "passages_q9.json"


def _default_answer_keys_path() -> Path:
    # If you store answer keys elsewhere, update this.
    return _data_dir() / "answer_keys.json"


# ----------------------------
# Cache (speed)
# ----------------------------

_CACHE_JSON: Dict[str, Any] = {}


def _read_json_cached(path: Path) -> Any:
    key = str(path)
    if key in _CACHE_JSON:
        return _CACHE_JSON[key]
    payload = json.loads(path.read_text(encoding="utf-8"))
    _CACHE_JSON[key] = payload
    return payload


def clear_bank_cache() -> None:
    """Useful during development if you re-generate JSON files frequently."""
    _CACHE_JSON.clear()


# ----------------------------
# Existing schema validation (MCQ 1-8)
# Keep behavior identical to your current loader.
# ----------------------------

def _validate_passages_payload(payload: Any) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["Root must be an object."]

    passages = payload.get("passages")
    if not isinstance(passages, list):
        return False, ["'passages' must be a list."]

    for pi, p in enumerate(passages):
        if not isinstance(p, dict):
            errors.append(f"passages[{pi}] must be an object.")
            continue

        for k in ("id", "title", "content", "questions"):
            if k not in p:
                errors.append(f"passages[{pi}] missing key '{k}'.")

        qs = p.get("questions")
        if not isinstance(qs, list):
            errors.append(f"passages[{pi}].questions must be a list.")
            continue

        for qi, q in enumerate(qs):
            if not isinstance(q, dict):
                errors.append(f"passages[{pi}].questions[{qi}] must be an object.")
                continue

            for k in ("id", "stem", "choices", "correct_index"):
                if k not in q:
                    errors.append(f"passages[{pi}].questions[{qi}] missing key '{k}'.")

            choices = q.get("choices")
            if not isinstance(choices, list) or len(choices) != 4:
                errors.append(f"{q.get('id', 'unknown')}: choices must have length 4.")

            ci = q.get("correct_index")
            if not isinstance(ci, int) or ci < 0 or ci > 3:
                errors.append(f"{q.get('id', 'unknown')}: correct_index must be int in [0, 3].")

    return len(errors) == 0, errors


def _to_exam_set_from_passage(p: Dict[str, Any]) -> Dict[str, Any]:
    passage_text = str(p.get("content", "")).strip()
    title = str(p.get("title", "")).strip()
    pid = str(p.get("id", "")).strip()

    questions_out: List[Dict[str, Any]] = []
    for q in p.get("questions", []):
        choices_text = q.get("choices", [])
        correct_index = int(q.get("correct_index", 0))
        letters = ["A", "B", "C", "D"]

        choices = [(letters[i], str(choices_text[i]).strip()) for i in range(4)]
        correct_letter = letters[correct_index]

        questions_out.append(
            {
                "id": str(q.get("id", "")),
                "type": "single",
                "prompt": str(q.get("stem", "")).strip(),
                "choices": choices,
                "correct": [correct_letter],
                "explanation": q.get("explanation"),
            }
        )

    return {
        "id": f"reading-{pid}",
        "title": f"Reading Passage {pid}: {title}" if title else f"Reading Passage {pid}",
        "passage": passage_text,
        "questions": questions_out,
    }


def load_exam_set(
    passages_json_path: Optional[JsonPath] = None,
    *,
    passage_index: int = 0,
) -> BankLoadResult:
    """
    Backward-compatible loader for the original MCQ (Q1-8) bank.

    DO NOT CHANGE behavior: same validation, same title formatting,
    same passage_index modulo wrap warning, etc.
    """
    path = Path(passages_json_path) if passages_json_path else _default_passages_path()
    path = path.expanduser().resolve()

    warnings: List[str] = []

    if not path.exists():
        raise FileNotFoundError(f"passages.json not found: {path}")

    payload = _read_json_cached(path)
    ok, errors = _validate_passages_payload(payload)
    if not ok:
        raise ValueError("Invalid passages.json schema:\n" + "\n".join(errors[:50]))

    passages: List[Dict[str, Any]] = payload["passages"]
    if not passages:
        raise ValueError("passages.json contains zero passages.")

    idx = passage_index % len(passages)
    if idx != passage_index:
        warnings.append("passage_index out of range; wrapped by modulo.")

    exam_set = _to_exam_set_from_passage(passages[idx])

    if not exam_set["questions"]:
        warnings.append("Selected passage has zero questions after import/filtering.")

    return BankLoadResult(exam_set=exam_set, warnings=warnings)


# ----------------------------
# New: Q9 bank loader (Insert Sentence)
# Will not affect old MCQ loader.
# ----------------------------

def _load_answer_key_map(answer_keys_path: Optional[JsonPath]) -> Dict[str, str]:
    """
    Returns mapping: question_id -> correct_letter (A-D).

    Supports these common formats:
    1) {"P01-Q09":"A", "P01-Q10":["A","C","E"], ...}
    2) {"P01": {"9":"A", "10":["A","C","E"]}, ...}  (we only need Q9)
    3) {"passages":[{"passage_id":"P01","q9":"A",...}, ...]}
    If unrecognized or file missing, returns {} without raising.
    """
    if not answer_keys_path:
        return {}

    path = Path(answer_keys_path).expanduser().resolve()
    if not path.exists():
        return {}

    try:
        payload = _read_json_cached(path)
    except Exception:
        return {}

    out: Dict[str, str] = {}

    # Case 1: flat dict
    if isinstance(payload, dict):
        # If keys look like question ids directly
        for k, v in payload.items():
            if isinstance(k, str) and isinstance(v, str):
                if k.endswith("Q09") and v in ("A", "B", "C", "D"):
                    out[k] = v

        # Case 2: nested by passage id
        # Example: {"P01":{"9":"A",...}, ...}
        for pk, pv in payload.items():
            if isinstance(pk, str) and isinstance(pv, dict):
                v = pv.get("9") or pv.get("q9")
                if isinstance(v, str) and v in ("A", "B", "C", "D"):
                    qid = f"{pk}-Q09" if not pk.endswith("-Q09") else pk
                    out[qid] = v

        # Case 3: {"passages":[...]}
        passages = payload.get("passages")
        if isinstance(passages, list):
            for item in passages:
                if not isinstance(item, dict):
                    continue
                pid = item.get("passage_id") or item.get("id")
                v = item.get("q9") or item.get("9")
                if isinstance(pid, str) and isinstance(v, str) and v in ("A", "B", "C", "D"):
                    out[f"{pid}-Q09"] = v

    return out


def _validate_q9_payload(payload: Any) -> Tuple[bool, List[str]]:
    """
    Lightweight validation for passages_q9.json (generated by your importer).
    We validate only what we need for stable runtime rendering.
    """
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["Root must be an object."]

    passages = payload.get("passages")
    if not isinstance(passages, list):
        return False, ["'passages' must be a list."]

    for pi, p in enumerate(passages):
        if not isinstance(p, dict):
            errors.append(f"passages[{pi}] must be an object.")
            continue

        for k in ("passage_id", "title", "questions"):
            if k not in p:
                errors.append(f"passages[{pi}] missing key '{k}'.")

        qs = p.get("questions")
        if not isinstance(qs, list) or not qs:
            errors.append(f"{p.get('passage_id','unknown')}: questions must be a non-empty list.")
            continue

        # We expect exactly one Q9 question per passage in this bank, but allow more
        for qi, q in enumerate(qs):
            if not isinstance(q, dict):
                errors.append(f"passages[{pi}].questions[{qi}] must be an object.")
                continue

            if q.get("question_type") != "insert_sentence":
                errors.append(f"{q.get('id','unknown')}: question_type must be 'insert_sentence'.")

            for k in ("id", "paragraph_text", "sentence", "options"):
                if k not in q:
                    errors.append(f"{q.get('id','unknown')}: missing key '{k}'.")

            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) != 4:
                errors.append(f"{q.get('id','unknown')}: options must be a list of length 4.")

    return len(errors) == 0, errors


def _to_exam_set_from_q9_passage(
    p: Dict[str, Any],
    *,
    answer_map: Dict[str, str],
) -> Dict[str, Any]:
    """
    Convert one Q9 passage record to your standard exam_set structure:
    {id,title,passage,questions:[{id,type,prompt,choices,correct,...}]}
    """
    pid = str(p.get("passage_id", "")).strip()
    title = str(p.get("title", "")).strip()
    qs = p.get("questions", [])

    # In this Q9 bank we show the paragraph excerpt as the "passage" field
    # (front-end can render it as passage area)
    # Use the first question's paragraph_text for passage content.
    first_q = qs[0] if qs else {}
    passage_text = str(first_q.get("paragraph_text", "")).strip()

    questions_out: List[Dict[str, Any]] = []
    for q in qs:
        qid = str(q.get("id", "")).strip()
        sentence = str(q.get("sentence", "")).strip()

        # You want ABCD buttons. We'll keep the same "choices" shape as MCQ:
        # list[ (letter, text) ]
        letters = ["A", "B", "C", "D"]
        choices = [(letters[i], f"Insert at [{letters[i]}]") for i in range(4)]

        correct_letter = answer_map.get(qid)  # may be None
        correct_list = [correct_letter] if correct_letter in letters else []

        prompt = (
            "Look at the four squares [A], [B], [C], [D] that indicate where the following sentence could be added.\n"
            f"Sentence: {sentence}\n"
            "Where would the sentence best fit?"
        )

        questions_out.append(
            {
                "id": qid,
                "type": "single",
                "prompt": prompt,
                "choices": choices,
                "correct": correct_list,  # empty list allowed if no key
                "explanation": None,
                # Extra fields for templates that want richer rendering
                "meta": {
                    "question_type": "insert_sentence",
                    "paragraph_label": q.get("paragraph_label"),
                    "paragraph_text": q.get("paragraph_text"),
                    "sentence": q.get("sentence"),
                },
            }
        )

    return {
        "id": f"q9-{pid}",
        "title": f"Q9 Passage {pid}: {title}" if title else f"Q9 Passage {pid}",
        "passage": passage_text,
        "questions": questions_out,
    }


def load_q9_exam_set(
    q9_json_path: Optional[JsonPath] = None,
    *,
    passage_index: int = 0,
    answer_keys_path: Optional[JsonPath] = None,
) -> BankLoadResult:
    """
    New loader for Q9 bank (insert sentence). Independent from MCQ loader.
    """
    path = Path(q9_json_path) if q9_json_path else _default_q9_path()
    path = path.expanduser().resolve()

    warnings: List[str] = []

    if not path.exists():
        raise FileNotFoundError(f"passages_q9.json not found: {path}")

    payload = _read_json_cached(path)
    ok, errors = _validate_q9_payload(payload)
    if not ok:
        raise ValueError("Invalid passages_q9.json schema:\n" + "\n".join(errors[:50]))

    passages: List[Dict[str, Any]] = payload["passages"]
    if not passages:
        raise ValueError("passages_q9.json contains zero passages.")

    idx = passage_index % len(passages)
    if idx != passage_index:
        warnings.append("passage_index out of range; wrapped by modulo.")

    answer_map = _load_answer_key_map(answer_keys_path or _default_answer_keys_path())

    exam_set = _to_exam_set_from_q9_passage(passages[idx], answer_map=answer_map)

    if not exam_set["questions"]:
        warnings.append("Selected Q9 passage has zero questions after import/filtering.")

    # Optional: surface importer warnings if present
    src_warnings = payload.get("warnings")
    if isinstance(src_warnings, list) and src_warnings:
        warnings.append(f"Bank warnings: {len(src_warnings)} (see import_report_q9.json)")

    return BankLoadResult(exam_set=exam_set, warnings=warnings)


# ----------------------------
# Unified entry (NEW) - does not affect old callers
# ----------------------------

def load_exam_set_by_bank(
    bank_key: str,
    *,
    passage_index: int = 0,
    bank_path: Optional[JsonPath] = None,
    answer_keys_path: Optional[JsonPath] = None,
) -> BankLoadResult:
    """
    Unified loader for multiple banks without breaking the legacy API.

    bank_key:
      - "mcq": uses passages.json schema (Q1-8)
      - "q9":  uses passages_q9.json schema (insert sentence)
    """
    key = (bank_key or "mcq").lower().strip()
    if key == "mcq":
        return load_exam_set(bank_path, passage_index=passage_index)
    if key == "q9":
        return load_q9_exam_set(bank_path, passage_index=passage_index, answer_keys_path=answer_keys_path)
    raise KeyError(f"Unknown bank_key: {bank_key}")
