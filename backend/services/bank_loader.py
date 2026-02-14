from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class BankLoadResult:
    exam_set: Dict[str, Any]
    warnings: List[str]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_passages_path() -> Path:
    return _project_root() / "data" / "passages.json"


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
    passages_json_path: Optional[str | Path] = None,
    *,
    passage_index: int = 0,
) -> BankLoadResult:
    path = Path(passages_json_path) if passages_json_path else _default_passages_path()
    path = path.expanduser().resolve()

    warnings: List[str] = []

    if not path.exists():
        raise FileNotFoundError(f"passages.json not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
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
