from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


# Cached in-process bank to avoid reading JSON repeatedly
_Q10_BANK: Optional[List[Dict[str, Any]]] = None
_Q10_BY_PASSAGE: Optional[Dict[int, Dict[str, Any]]] = None


def _default_bank_path() -> Path:
    # backend/services/q10_repo.py -> backend/
    backend_dir = Path(__file__).resolve().parents[1]
    return backend_dir / "data" / "q10_bank.json"


def load_q10_bank(bank_path: Optional[Path] = None, force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    Load Q10 bank from JSON and cache it in memory.
    JSON format: a list of objects, each has keys: passage_no, title, q10.
    """
    global _Q10_BANK, _Q10_BY_PASSAGE

    if _Q10_BANK is not None and not force_reload:
        return _Q10_BANK

    path = bank_path or _default_bank_path()
    if not path.exists():
        raise FileNotFoundError(f"q10_bank.json not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("q10_bank.json must be a JSON list")

    by_passage: Dict[int, Dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        pno = item.get("passage_no")
        if isinstance(pno, int):
            by_passage[pno] = item

    _Q10_BANK = data
    _Q10_BY_PASSAGE = by_passage
    return _Q10_BANK


def get_q10_item(passage_no: int) -> Optional[Dict[str, Any]]:
    """
    Return the full item: {"passage_no":..., "title":..., "q10": {...}}
    """
    load_q10_bank()
    assert _Q10_BY_PASSAGE is not None
    return _Q10_BY_PASSAGE.get(passage_no)


def get_q10_question(passage_no: int) -> Optional[Dict[str, Any]]:
    """
    Return the normalized Q10 question dict, or None.

    Key fix:
      - Force id to "P{passage_no}-Q10" so it matches 1-9 style and result display logic.
    """
    item = get_q10_item(passage_no)
    if not item:
        return None

    q10 = item.get("q10")
    if not isinstance(q10, dict):
        return None

    out = dict(q10)

    # ✅ unify id format with other questions
    out["id"] = f"P{int(passage_no)}-Q10"

    # sensible defaults (won't break if your bank already sets them)
    if not out.get("type"):
        out["type"] = "summary"

    # ensure prompt field exists if bank used "stem"
    if "prompt" not in out and "stem" in out:
        out["prompt"] = out.get("stem") or ""

    # (optional) keep a tiny meta marker for debugging
    meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
    meta = dict(meta)
    meta.setdefault("question_no", 10)
    out["meta"] = meta

    return out
