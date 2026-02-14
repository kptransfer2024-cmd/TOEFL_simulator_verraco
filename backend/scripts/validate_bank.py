from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _find_backend_dir() -> Path:
    here = Path(__file__).resolve()
    backend_dir = here.parents[1]
    if backend_dir.name != "backend":
        raise RuntimeError(f"Unexpected scripts location: {here}")
    return backend_dir


def _ensure_sys_path(backend_dir: Path) -> None:
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


@dataclass(frozen=True)
class ValidationResult:
    passages: int
    questions: int
    warnings: List[str]
    errors: List[str]


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to load JSON: {path} ({e})") from e


def _validate_payload(payload: Dict[str, Any], strict: bool = True) -> ValidationResult:
    warnings: List[str] = []
    errors: List[str] = []

    passages = payload.get("passages")
    if not isinstance(passages, list):
        return ValidationResult(passages=0, questions=0, warnings=[], errors=["'passages' must be a list"])

    total_q = 0

    for pi, p in enumerate(passages):
        if not isinstance(p, dict):
            errors.append(f"passages[{pi}] must be an object")
            continue

        for k in ("id", "title", "content", "questions"):
            if k not in p:
                errors.append(f"passages[{pi}] missing key '{k}'")

        pid = p.get("id", f"idx={pi}")
        title = p.get("title")
        content = p.get("content")
        qs = p.get("questions")

        if strict:
            if not isinstance(pid, str) or not pid.strip():
                errors.append(f"passages[{pi}].id must be a non-empty string")
            if not isinstance(title, str) or not title.strip():
                errors.append(f"passages[{pi}].title must be a non-empty string")
            if not isinstance(content, str) or not content.strip():
                warnings.append(f"passage {pid}: empty content")

        if not isinstance(qs, list):
            errors.append(f"passages[{pi}].questions must be a list")
            continue

        if len(qs) == 0:
            warnings.append(f"passage {pid}: 0 questions")

        for qi, q in enumerate(qs):
            total_q += 1
            if not isinstance(q, dict):
                errors.append(f"passage {pid} questions[{qi}] must be an object")
                continue

            for k in ("id", "stem", "choices", "correct_index"):
                if k not in q:
                    errors.append(f"passage {pid} questions[{qi}] missing key '{k}'")

            qid = q.get("id", f"{pid}#q{qi}")

            stem = q.get("stem")
            choices = q.get("choices")
            correct_index = q.get("correct_index")

            if strict:
                if not isinstance(qid, str) or not qid.strip():
                    errors.append(f"passage {pid} question[{qi}]: id must be a non-empty string")
                if not isinstance(stem, str) or not stem.strip():
                    errors.append(f"{qid}: stem must be a non-empty string")

            if not isinstance(choices, list) or len(choices) != 4:
                errors.append(f"{qid}: choices must be a list of length 4")
            else:
                if strict:
                    for ci, c in enumerate(choices):
                        if not isinstance(c, str) or not c.strip():
                            errors.append(f"{qid}: choices[{ci}] must be a non-empty string")

            if not isinstance(correct_index, int) or correct_index < 0 or correct_index > 3:
                errors.append(f"{qid}: correct_index must be an int in [0, 3]")

            expl = q.get("explanation")
            if expl is not None and strict and not isinstance(expl, str):
                errors.append(f"{qid}: explanation must be a string or null")

    return ValidationResult(passages=len(passages), questions=total_q, warnings=warnings, errors=errors)


def main() -> None:
    backend_dir = _find_backend_dir()
    _ensure_sys_path(backend_dir)

    parser = argparse.ArgumentParser(description="Validate passages.json schema and print summary stats.")
    parser.add_argument(
        "--json",
        default=str(backend_dir / "data" / "passages.json"),
        help="Path to passages.json",
    )
    parser.add_argument("--max-print", type=int, default=30, help="Max warnings/errors to print")
    parser.add_argument("--non-strict", action="store_true", help="Relax some string checks")
    args = parser.parse_args()

    json_path = Path(args.json).expanduser().resolve()

    if not json_path.exists():
        print(f"[ERROR] passages.json not found: {json_path}")
        sys.exit(2)

    payload = _load_json(json_path)
    result = _validate_payload(payload, strict=not args.non_strict)

    print("Validation summary")
    print(f"- File: {json_path}")
    print(f"- Passages: {result.passages}")
    print(f"- Questions: {result.questions}")
    print(f"- Warnings: {len(result.warnings)}")
    print(f"- Errors: {len(result.errors)}")

    if result.warnings:
        print("\nWarnings (first {}):".format(min(args.max_print, len(result.warnings))))
        for w in result.warnings[: args.max_print]:
            print(f"- {w}")

    if result.errors:
        print("\nErrors (first {}):".format(min(args.max_print, len(result.errors))))
        for e in result.errors[: args.max_print]:
            print(f"- {e}")
        sys.exit(1)

    print("\n[OK] passages.json passed validation.")
    sys.exit(0)


if __name__ == "__main__":
    main()
