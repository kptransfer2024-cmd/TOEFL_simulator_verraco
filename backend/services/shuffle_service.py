from __future__ import annotations

import copy

import random
from typing import Any, Dict, List, Tuple

_LETTERS = ("A", "B", "C", "D")


def _as_letter_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip().upper()
        return [s] if s else []
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            if x is None:
                continue
            s = str(x).strip().upper()
            if s:
                out.append(s)
        return out
    s = str(v).strip().upper()
    return [s] if s else []


def _get_correct_letters(q: Dict[str, Any]) -> List[str]:
    for key in ("correct_letters",):
        v = q.get(key)
        lst = _as_letter_list(v)
        if lst:
            return lst

    for key in ("correct", "answer", "correct_letter"):
        v = q.get(key)
        lst = _as_letter_list(v)
        if lst:
            return lst

    ci = q.get("correct_index")
    if isinstance(ci, int) and 0 <= ci < 4:
        return [_LETTERS[ci]]

    meta = q.get("meta")
    if isinstance(meta, dict):
        for key in ("correct_letters",):
            v = meta.get(key)
            lst = _as_letter_list(v)
            if lst:
                return lst
        for key in ("correct", "answer", "correct_letter"):
            v = meta.get(key)
            lst = _as_letter_list(v)
            if lst:
                return lst
        ci2 = meta.get("correct_index")
        if isinstance(ci2, int) and 0 <= ci2 < 4:
            return [_LETTERS[ci2]]

    return []


def _set_correct_letters(q: Dict[str, Any], new_letters: List[str]) -> None:
    qtype = str(q.get("type") or "single").strip().lower()
    is_multi = (qtype == "multi") or (len(new_letters) > 1)

    if is_multi:
        q["correct_letters"] = list(new_letters)
        q["correct"] = list(new_letters)
        q.pop("correct_letter", None)
        q.pop("correct_index", None)
    else:
        letter = new_letters[0] if new_letters else "A"
        q["correct_letter"] = letter
        q["correct"] = [letter]
        q["correct_index"] = _LETTERS.index(letter) if letter in _LETTERS else 0
        q.pop("correct_letters", None)


def _shuffle_choices_one(q: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    q2: Dict[str, Any] = copy.deepcopy(q)

    choices = q2.get("choices")
    if not isinstance(choices, list) or len(choices) != 4:
        return q2

    parsed: List[Tuple[str, str]] = []
    for item in choices:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            parsed.append((str(item[0]).strip().upper(), str(item[1])))
        elif isinstance(item, dict) and "label" in item and "text" in item:
            parsed.append((str(item["label"]).strip().upper(), str(item["text"])))
        else:
            parsed.append(("", str(item)))

    if len(parsed) != 4:
        return q2

    correct_before = _get_correct_letters(q2)

    indexed = list(enumerate(parsed))
    rng.shuffle(indexed)

    old_index_to_new_index = {}
    for new_i, (old_i, _) in enumerate(indexed):
        old_index_to_new_index[old_i] = new_i

    label_to_old_index = {}
    for old_i, (lab, _txt) in enumerate(parsed):
        if lab in _LETTERS:
            label_to_old_index[lab] = old_i
        else:
            label_to_old_index[_LETTERS[old_i]] = old_i

    new_correct: List[str] = []
    for lab in correct_before:
        if lab not in _LETTERS:
            continue
        old_i = label_to_old_index.get(lab)
        if old_i is None:
            continue
        new_i = old_index_to_new_index.get(old_i)
        if new_i is None:
            continue
        new_correct.append(_LETTERS[new_i])

    new_choices: List[Tuple[str, str]] = []
    for i, (_old_i, (_old_lab, txt)) in enumerate(indexed):
        new_choices.append((_LETTERS[i], txt))

    q2["choices"] = new_choices
    _set_correct_letters(q2, new_correct or ["A"])

    meta = q2.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        q2["meta"] = meta
    meta["shuffled_choices"] = True
    # after meta["shuffled_choices"] = True
    old_to_new = {}
    new_to_old = {}
    for old_i, new_i in old_index_to_new_index.items():
        old_lab = _LETTERS[old_i]
        new_lab = _LETTERS[new_i]
        old_to_new[old_lab] = new_lab
        new_to_old[new_lab] = old_lab

    meta["old_to_new_letter"] = old_to_new
    meta["new_to_old_letter"] = new_to_old

    return q2


def shuffle_exam_set(exam_set: Dict[str, Any], seed: int) -> Dict[str, Any]:
    """
    Shuffle ONLY the choices within each question.
    Do NOT reorder questions.
    Also remaps correct answers to match the shuffled choices.
    """
    out: Dict[str, Any] = copy.deepcopy(exam_set)
    rng = random.Random(int(seed))

    qs = out.get("questions")
    if not isinstance(qs, list) or not qs:
        return out

    # Keep original question order
    normalized_qs: List[Dict[str, Any]] = []
    for q in qs:
        if isinstance(q, dict):
            normalized_qs.append(q)
    out["questions"] = normalized_qs

    # Shuffle choices per question (deterministic, stable per attempt)
    shuffled_questions: List[Dict[str, Any]] = []
    for idx, q in enumerate(out["questions"]):
        # Derive a per-question seed so each question shuffles independently but reproducibly
        q_seed = (int(seed) * 1000003) + idx
        q_rng = random.Random(q_seed)
        shuffled_questions.append(_shuffle_choices_one(q, q_rng))

    out["questions"] = shuffled_questions

    # Preserve seq if you already set it elsewhere; otherwise ensure it's stable 1..N
    for i, q in enumerate(out["questions"], start=1):
        meta = q.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            q["meta"] = meta
        if "seq" not in meta:
            meta["seq"] = i

    return out


