from __future__ import annotations



import json
import random
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import store
from core.store import ATTEMPTS
from services.shuffle_service import shuffle_exam_set
from services.q10_repo import get_q10_question


# ----------------------------
# Types
# ----------------------------

@dataclass(frozen=True)
class BankLoadResult:
    exam_set: Dict[str, Any]
    warnings: List[str]


# ----------------------------
# Constants
# ----------------------------

_LETTERS = ("A", "B", "C", "D")
_LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}
_INDEX_TO_LETTER = {0: "A", 1: "B", 2: "C", 3: "D"}

_QID_RE = re.compile(
    r"^(?:P(?P<pid>\d{1,3})-Q(?P<q>\d{1,2})|(?P<pid2>\d{1,3})-(?P<q2>\d{1,2}))$",
    re.I,
)

_JSON_CACHE: Dict[str, Any] = {}


# ----------------------------
# Paths
# ----------------------------

def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _data_dir() -> Path:
    return _project_root() / "data"


def _bank_path(bank_key: str) -> Path:
    key = (bank_key or "mcq").lower().strip()
    if key == "q9":
        return _data_dir() / "passages_q9.json"
    return _data_dir() / "passages.json"


def _q9_path() -> Path:
    return _project_root() / "data" / "passages_q9.json"


# ----------------------------
# JSON cache
# ----------------------------

def _read_json(path: Path) -> Any:
    p = path.expanduser().resolve()
    key = str(p)
    if key in _JSON_CACHE:
        return _JSON_CACHE[key]
    payload = json.loads(p.read_text(encoding="utf-8"))
    _JSON_CACHE[key] = payload
    return payload


def clear_json_cache() -> None:
    _JSON_CACHE.clear()


# ----------------------------
# Helpers
# ----------------------------

def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _pick_first_key(d: Dict[str, Any], keys: Tuple[str, ...]) -> Tuple[str, Any]:
    for k in keys:
        if k in d:
            return k, d.get(k)
    return "", None


def _to_letter_from_index(idx: Any) -> Optional[str]:
    try:
        i = int(idx)
    except Exception:
        return None
    if 0 <= i < 4:
        return _INDEX_TO_LETTER[i]
    return None


def _normalize_choices(raw_choices: Any, warnings: List[str], qid: str) -> List[str]:
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


def _normalize_correct_index(q: Dict[str, Any], warnings: List[str], qid: str) -> int:
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


def _norm_pid(pid: Any) -> str:
    s = _as_str(pid).upper()
    if not s:
        return ""

    if s.startswith("READING-"):
        s = s.replace("READING-", "").strip()

    if s.startswith("P"):
        tail = s[1:].strip()
        if tail.isdigit():
            return f"P{int(tail)}"
        return s

    if s.isdigit():
        return f"P{int(s)}"

    return s


def _ensure_seq(exam_set: Dict[str, Any]) -> None:
    qs = exam_set.get("questions")
    if not isinstance(qs, list):
        return
    for i, q in enumerate(qs, start=1):
        if not isinstance(q, dict):
            continue
        meta = q.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            q["meta"] = meta
        if "seq" not in meta:
            meta["seq"] = i


def _get_question_by_seq(exam_set: Dict[str, Any], seq: int) -> Optional[Dict[str, Any]]:
    qs = exam_set.get("questions")
    if not isinstance(qs, list):
        return None
    for q in qs:
        if not isinstance(q, dict):
            continue
        meta = q.get("meta") if isinstance(q.get("meta"), dict) else {}
        if int(meta.get("seq") or 0) == int(seq):
            return q
    return None


# ----------------------------
# Passage normalization
# ----------------------------

def _normalize_passage_schema(p: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
    _, pid_val = _pick_first_key(p, ("id", "passage_id"))
    pid = _as_str(pid_val)
    title = _as_str(p.get("title"))

    _, content_val = _pick_first_key(p, ("content", "text", "passage"))
    content = _as_str(content_val)

    qs_raw = p.get("questions")
    if not isinstance(qs_raw, list):
        warnings.append(f"passage {pid or 'unknown'}: questions missing or not a list; replaced with empty list.")
        qs_raw = []

    if not content and qs_raw and isinstance(qs_raw[0], dict):
        para = _as_str(qs_raw[0].get("paragraph_text"))
        if para:
            content = para

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

        qtype = _as_str(q.get("question_type"))
        if qtype == "insert_sentence":
            sentence = _as_str(q.get("sentence"))
            if sentence:
                stem = (
                    "Look at the four squares [A], [B], [C], [D] that indicate where the following sentence could be added.\n"
                    f"Sentence: {sentence}\n"
                    "Where would the sentence best fit?"
                )
            raw_choices = q.get("options") or q.get("choices")
            if raw_choices is None:
                raw_choices = [
                    {"label": "A", "text": "Insert at [A]"},
                    {"label": "B", "text": "Insert at [B]"},
                    {"label": "C", "text": "Insert at [C]"},
                    {"label": "D", "text": "Insert at [D]"},
                ]
        else:
            raw_choices = q.get("choices")

        choices = _normalize_choices(raw_choices, warnings, qid)
        ci = _normalize_correct_index(q, warnings, qid)
        explanation = q.get("explanation")

        meta: Dict[str, Any] = {}
        if qtype == "insert_sentence":
            meta = {
                "question_type": "insert_sentence",
                "paragraph_label": q.get("paragraph_label"),
                "paragraph_text": q.get("paragraph_text"),
                "sentence": q.get("sentence"),
            }

        qs_norm.append(
            {
                "id": qid,
                "stem": stem,
                "choices": choices,
                "correct_index": int(ci),
                "explanation": explanation,
                "meta": meta,
            }
        )

    return {
        "id": pid,
        "title": title,
        "content": content,
        "questions": qs_norm,
    }


def _validate_passages_payload_loose(payload: Any) -> Tuple[bool, List[str]]:
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

        if not isinstance(ci, int):
            ci = 0
        if ci < 0 or ci > 3:
            ci = 0

        correct_letter = _INDEX_TO_LETTER.get(ci, "A")
        choices_pairs: List[Tuple[str, str]] = [(_LETTERS[i], _as_str(raw_choices[i])) for i in range(4)]

        out_q: Dict[str, Any] = {
            "id": qid,
            "type": "single",
            "prompt": stem,
            "choices": choices_pairs,
            "correct": [correct_letter],
            "correct_index": ci,
            "correct_letter": correct_letter,
            "explanation": q.get("explanation"),
        }

        meta = q.get("meta")
        if isinstance(meta, dict) and meta:
            out_q["meta"] = meta

        questions_out.append(out_q)

    label = f"Reading Passage {pid}" if pid else "Reading Passage"
    if title:
        label = f"{label}: {title}"

    return {
        "id": f"reading-{pid}" if pid else "reading",
        "title": label,
        "passage": passage_text,
        "questions": questions_out,
    }


# ----------------------------
# Bank-aware loader
# ----------------------------

def _load_exam_set_from_passages(
    bank_key: str,
    passages_path: Optional[str | Path],
    passage_index: int,
) -> BankLoadResult:
    path = Path(passages_path) if passages_path else _bank_path(bank_key)
    path = path.expanduser().resolve()

    warnings: List[str] = []

    if not path.exists():
        raise FileNotFoundError(f"bank not found: {path}")

    payload = _read_json(path)
    ok, errors = _validate_passages_payload_loose(payload)
    if not ok:
        raise ValueError(f"Invalid bank payload ({path.name}):\n" + "\n".join(errors))

    passages_raw: List[Dict[str, Any]] = payload.get("passages", [])
    if not passages_raw:
        raise ValueError(f"{path.name} contains zero passages.")

    idx = passage_index % len(passages_raw)
    if idx != passage_index:
        warnings.append("passage_index out of range; wrapped by modulo.")

    p_norm = _normalize_passage_schema(passages_raw[idx], warnings)
    exam_set = _passage_to_exam_set(p_norm)

    if not exam_set.get("questions"):
        warnings.append("Selected passage has zero questions after normalization.")

    return BankLoadResult(exam_set=exam_set, warnings=warnings)


def _derive_passage_index(seed: int, passages_count: int) -> int:
    rng = random.Random(seed)
    return rng.randrange(passages_count)


def _count_passages(bank_key: str = "mcq", passages_path: Optional[str | Path] = None) -> int:
    path = Path(passages_path) if passages_path else _bank_path(bank_key)
    path = path.expanduser().resolve()
    try:
        payload = _read_json(path)
    except Exception:
        return 1

    passages = payload.get("passages")
    if isinstance(passages, list) and passages:
        return len(passages)
    return 1


# ----------------------------
# Q9 merge
# ----------------------------

def _load_q9_question_for_passage(passage_id: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
    path = _q9_path().expanduser().resolve()
    if not path.exists():
        warnings.append(f"Q9 bank missing: {path}")
        return None

    payload = _read_json(path)
    passages = payload.get("passages", [])
    if not isinstance(passages, list) or not passages:
        warnings.append("Q9 bank has no passages.")
        return None

    want = _norm_pid(passage_id)
    if not want:
        warnings.append("Q9 lookup: empty passage_id after normalization.")
        return None

    target: Optional[Dict[str, Any]] = None
    for p in passages:
        if not isinstance(p, dict):
            continue
        got_raw = p.get("passage_id") if "passage_id" in p else p.get("id")
        got = _norm_pid(got_raw)
        if got and got == want:
            target = p
            break

    if not target:
        warnings.append(f"{want}: Q9 passage not found in passages_q9.json.")
        return None

    p_norm = _normalize_passage_schema(target, warnings)
    qs = p_norm.get("questions", [])
    if not isinstance(qs, list) or not qs:
        warnings.append(f"{want}: Q9 questions empty after normalization.")
        return None

    return qs[0]

def _lookup_q10_correct_from_answer_keys(passage_no: int, warnings: List[str]) -> Optional[str]:
    """
    Read data/answer_keys.json and return Q10 correct string like "ABC" for passage_no (1..50).
    Uses _read_json cache.
    """
    try:
        path = _data_dir() / "answer_keys.json"
        payload = _read_json(path)

        if not isinstance(payload, list):
            warnings.append("answer_keys.json root is not a list.")
            return None

        row = None
        for r in payload:
            if not isinstance(r, dict):
                continue
            try:
                rid = int(r.get("id") or 0)
            except Exception:
                continue
            if rid == int(passage_no):
                row = r
                break

        if not row:
            warnings.append(f"P{passage_no}: not found in answer_keys.json.")
            return None

        answers = row.get("answers")
        if not isinstance(answers, list) or len(answers) < 10:
            warnings.append(f"P{passage_no}: invalid answers list in answer_keys.json.")
            return None

        q10 = answers[9]  # Q10 is index 9
        if not isinstance(q10, str):
            warnings.append(f"P{passage_no}: Q10 answer is not a string.")
            return None

        s = q10.strip().upper()
        if not s:
            warnings.append(f"P{passage_no}: Q10 answer empty.")
            return None

        return s
    except Exception as e:
        warnings.append(f"answer_keys.json read failed: {e}")
        return None



def _load_q10_question_for_passage(passage_id: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
    """
    Build a Q10 question in the same shape as exam_set["questions"] items.
    """
    want = _norm_pid(passage_id)
    if not want:
        warnings.append("Q10 lookup: empty passage_id after normalization.")
        return None

    # want looks like "P9" or "P27"
    m = re.match(r"^P(\d+)$", want, re.I)
    if not m:
        warnings.append(f"{want}: Q10 lookup: invalid passage_id format.")
        return None

    passage_no = int(m.group(1))
    q10 = get_q10_question(passage_no)
    if not q10:
        warnings.append(f"{want}: Q10 not found in q10_bank.json.")
        return None

    qid = _as_str(q10.get("qid")) or f"p{passage_no:02d}_q10"
    prompt = _as_str(q10.get("prompt"))
    intro = _as_str(q10.get("intro"))
    max_sel = int(q10.get("max_selections") or 3)

    choices_raw = q10.get("choices", [])
    choices_out: List[Tuple[str, str]] = []
    if isinstance(choices_raw, list):
        for item in choices_raw:
            if not isinstance(item, dict):
                continue
            cid = _as_str(item.get("id")).upper()
            text = _as_str(item.get("text"))
            if cid and text:
                choices_out.append((cid, text))

    if len(choices_out) != 6:
        warnings.append(f"{qid}: Q10 choices expected 6, got {len(choices_out)}.")
        return None
    
    correct_q10 = _lookup_q10_correct_from_answer_keys(passage_no, warnings)
    if not correct_q10:
        warnings.append(f"{qid}: Q10 correct not injected (missing in answer_keys.json).")

    return {
        "id": qid,
        "type": "summary",
        "prompt": prompt,
        "intro": intro,
        "max_selections": max_sel,
        "choices": choices_out,
        # important: grader will now be able to score Q10
        "correct": correct_q10,  # like "ABC"
    }




def pick_full_exam_set_for_attempt(seed: int) -> Dict[str, Any]:
    count = _count_passages("mcq", None)
    passage_index = _derive_passage_index(seed, passages_count=count)
    res = _load_exam_set_from_passages("mcq", None, passage_index=passage_index)

    exam_set = res.exam_set
    warnings = res.warnings

    raw_id = _as_str(exam_set.get("id"))
    passage_id = _norm_pid(raw_id)
    if not passage_id:
        warnings.append("full_set: failed to derive passage_id; skipped Q9/Q10 merge.")
        _ensure_seq(exam_set)
        return exam_set

    # ---- Q9 merge (your original logic, unchanged) ----
    q9_norm = _load_q9_question_for_passage(passage_id, warnings)
    if q9_norm:
        qid = _as_str(q9_norm.get("id")) or f"{passage_id}-9"
        stem = _as_str(q9_norm.get("stem"))
        raw_choices = q9_norm.get("choices", ["", "", "", ""])
        ci = q9_norm.get("correct_index", 0)

        if not isinstance(ci, int) or ci < 0 or ci > 3:
            ci = 0

        correct_letter = _INDEX_TO_LETTER.get(ci, "A")
        choices_out: List[Tuple[str, str]] = [(_LETTERS[i], _as_str(raw_choices[i])) for i in range(4)]

        q9_out: Dict[str, Any] = {
            "id": qid,
            "type": "single",
            "prompt": stem,
            "choices": choices_out,
            "correct": [correct_letter],
            "correct_index": ci,
            "correct_letter": correct_letter,
            "explanation": q9_norm.get("explanation"),
        }

        meta = q9_norm.get("meta")
        if isinstance(meta, dict) and meta:
            q9_out["meta"] = meta

        qs = exam_set.get("questions")
        if not isinstance(qs, list):
            qs = []
        if not any(isinstance(x, dict) and _as_str(x.get("id")) == qid for x in qs):
            exam_set["questions"] = qs + [q9_out]

    # ---- Q10 merge (new, minimal) ----
    q10_out = _load_q10_question_for_passage(passage_id, warnings)
    if q10_out:
        qs = exam_set.get("questions")
        if not isinstance(qs, list):
            qs = []
        q10_id = _as_str(q10_out.get("id"))
        if not any(isinstance(x, dict) and _as_str(x.get("id")) == q10_id for x in qs):
            exam_set["questions"] = qs + [q10_out]

    _ensure_seq(exam_set)
    return exam_set



# ----------------------------
# Public API
# ----------------------------

def pick_exam_set() -> Dict[str, Any]:
    res = _load_exam_set_from_passages("mcq", None, passage_index=0)
    _ensure_seq(res.exam_set)
    return res.exam_set


def pick_exam_set_for_attempt(seed: int) -> Dict[str, Any]:
    count = _count_passages("mcq", None)
    passage_index = _derive_passage_index(seed, passages_count=count)
    res = _load_exam_set_from_passages("mcq", None, passage_index=passage_index)
    _ensure_seq(res.exam_set)
    return res.exam_set


def pick_exam_set_for_attempt_bank(seed: int, bank_key: str) -> Dict[str, Any]:
    count = _count_passages(bank_key, None)
    passage_index = _derive_passage_index(seed, passages_count=count)
    res = _load_exam_set_from_passages(bank_key, None, passage_index=passage_index)
    _ensure_seq(res.exam_set)
    return res.exam_set


def create_attempt(minutes: int, mode: str = "full", single_index: int = 1) -> str:
    store.ATTEMPT_COUNTER += 1
    attempt_id = str(store.ATTEMPT_COUNTER)

    seed = random.randint(1, 10**9)

    mode_n = (mode or "full").strip().lower()
    if mode_n not in {"full", "single"}:
        mode_n = "full"

    try:
        single_index_i = int(single_index)
    except Exception:
        single_index_i = 1
    single_index_i = max(1, min(10, single_index_i))

    raw_exam_set = pick_full_exam_set_for_attempt(seed)
    _ensure_seq(raw_exam_set)

    ATTEMPTS[attempt_id] = {
        "minutes": int(minutes),
        "started_at": int(time.time()),
        "submitted": False,
        "timed_out": False,
        "result": None,
        "raw_exam_set": raw_exam_set,
        "shuffle_seed": seed,
        "passage_seed": seed,
        "mode": mode_n,
        "single_index": single_index_i,
        "answers": {},
        "shuffled_exam_set": None,
    }
    return attempt_id


def get_attempt(attempt_id: str) -> Optional[dict]:
    return ATTEMPTS.get(attempt_id)


def get_exam_set_for_attempt(attempt: dict) -> dict:
    cached = attempt.get("shuffled_exam_set")
    if isinstance(cached, dict):
        return cached

    raw = attempt.get("raw_exam_set")
    if not isinstance(raw, dict):
        seed = int(attempt.get("passage_seed") or attempt.get("shuffle_seed") or 1)
        bank_key = _as_str(attempt.get("bank_key") or "mcq").lower().strip()
        raw = pick_exam_set_for_attempt_bank(seed, bank_key=bank_key)
        attempt["raw_exam_set"] = raw

    seed = int(attempt.get("shuffle_seed") or 1)

    shuffled = shuffle_exam_set(raw, seed=seed)
    _ensure_seq(shuffled)

    attempt["shuffled_exam_set"] = shuffled
    return shuffled


def duration_seconds(attempt: dict) -> int:
    return int(attempt["minutes"]) * 60
