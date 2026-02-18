from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional, Union
import re

# support many qid styles:
#   P11-Q10, p11_q10, p11-q10, P11Q10, 11-10, 11_q10, 11-q10
_RE_PATTERNS = [
    re.compile(r"^P(?P<pid>\d+)[-_]?Q(?P<qn>\d+)$", re.IGNORECASE),
    re.compile(r"^P(?P<pid>\d+)[-_]?(?:Q|q)(?P<qn>\d+)$", re.IGNORECASE),
    re.compile(r"^(?P<pid>\d+)[-_](?P<qn>\d+)$", re.IGNORECASE),
    re.compile(r"^(?P<pid>\d+)[-_]q(?P<qn>\d+)$", re.IGNORECASE),
    re.compile(r"^p(?P<pid>\d+)[-_]?q(?P<qn>\d+)$", re.IGNORECASE),
    re.compile(r"^p(?P<pid>\d+)[-_]?(?P<qn>\d+)$", re.IGNORECASE),
]

LETTERS = ["A", "B", "C", "D", "E", "F"]


def _display_qid(qid: str) -> str:
    """
    UI-only display id.
    Converts many internal formats into: "<passage>-<question>"
    Examples:
      P20-Q09 -> 20-9
      p11_q10 -> 11-10
      11-10   -> 11-10
    """
    if not qid:
        return ""
    s = str(qid).strip()
    for rx in _RE_PATTERNS:
        m = rx.match(s)
        if not m:
            continue
        try:
            pid = int(m.group("pid"))
            qn = int(m.group("qn"))
            return f"{pid}-{qn}"
        except Exception:
            break
    return s


def _normalize_letter_list(v: Any) -> List[str]:
    """
    Normalize values into uppercase letters list.
    Accepts:
      - "A"
      - ["A","C"]
      - "ABC"
      - "A,C"
      - 0/1/2 (or "012") meaning A/B/C mapping
    """
    if v is None:
        return []

    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            if x is None:
                continue
            s = str(x).strip().upper()
            if not s:
                continue
            out.append(s)
        # keep only A-F
        out2 = [x for x in out if x in LETTERS]
        return sorted(list(set(out2)))

    # scalar
    s = str(v).strip().upper()
    if not s:
        return []

    # remove separators
    s2 = s.replace(",", "").replace(" ", "")

    # "012" -> A,B,C mapping
    if s2.isdigit():
        out: List[str] = []
        for ch in s2:
            i = int(ch)
            if 0 <= i < len(LETTERS):
                out.append(LETTERS[i])
        return sorted(list(set(out)))

    # "ABC" -> ["A","B","C"]
    if re.fullmatch(r"[A-F]{2,}", s2):
        return sorted(list(set([ch for ch in s2 if ch in LETTERS])))

    # "A"
    if s2 in LETTERS:
        return [s2]

    return []


def _get_user_answer_from_sources(
    qid: str,
    answers: Optional[Dict[str, Any]] = None,
    form: Any = None,
) -> List[str]:
    """
    Pull user answers from:
      - answers dict (attempt["answers"]) with values like "A" or ["A","C"]
      - or a Starlette FormData (legacy)
    """
    qid_u = (qid or "").strip().upper()
    if not qid_u:
        return []

    # preferred: dict answers
    if isinstance(answers, dict):
        v = answers.get(qid) or answers.get(qid_u)
        return _normalize_letter_list(v)

    # legacy: form
    if form is not None:
        key = f"ans_{qid}"
        if hasattr(form, "getlist"):
            raw = form.getlist(key)
        else:
            vv = getattr(form, "get", lambda *_: None)(key, None)
            raw = vv if isinstance(vv, list) else ([vv] if vv is not None else [])
        return _normalize_letter_list(raw)

    return []


def _get_correct_answer(
    q: Dict[str, Any],
    correct_answers: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Prefer correct_answers mapping (answer_keys.json result), fallback to q["correct"].
    """
    qid = str(q.get("id", "")).strip()
    qid_u = qid.upper()

    if isinstance(correct_answers, dict):
        v = correct_answers.get(qid)
        if v is None:
            v = correct_answers.get(qid_u)
        if v is not None:
            return _normalize_letter_list(v)

    # fallback to embedded
    v2 = q.get("correct")
    if v2 is None:
        v2 = q.get("correct_letters") or q.get("correct_letter")
    return _normalize_letter_list(v2)


def _score_single(user: List[str], correct: List[str]) -> Tuple[int, int, bool]:
    max_points = 1
    if not correct:
        return 0, max_points, False
    if len(user) != 1:
        return 0, max_points, False
    # if correct list somehow has multiple (tolerant), allow membership
    ok = (user[0] == correct[0]) if len(correct) == 1 else (user[0] in correct)
    return (1 if ok else 0), max_points, ok


def _score_multi_exact(user: List[str], correct: List[str]) -> Tuple[int, int, bool]:
    """
    Multi-answer (non-summary) scoring: exact set match => 1 else 0.
    Keeps your 1-9 behavior stable if you ever have multi outside Q10.
    """
    max_points = 1
    if not correct:
        return 0, max_points, False
    ok = (set(user) == set(correct)) and len(user) > 0
    return (1 if ok else 0), max_points, ok


def _score_summary_q10(user: List[str], correct: List[str]) -> Tuple[int, int, bool]:
    """
    Q10 scoring:
      exact set match => 2
      otherwise => 0
    Unlimited selections are allowed; extra selections will fail exact match => 0.
    """
    max_points = 2
    if not correct:
        return 0, max_points, False
    if len(user) == 0:
        return 0, max_points, False
    ok = set(user) == set(correct)
    return (2 if ok else 0), max_points, ok


def scale_reading_score(score_points: int, total_points: int) -> int:
    """
    Map raw points to a TOEFL-like Reading scaled score (0-30).
    Primary target: your current form with total_points == 11 (9 singles + Q10=2).
    """
    if total_points == 11:
        table = {
            11: 30,
            10: 29,
            9: 28,
            8: 27,
            7: 26,
            6: 25,
            5: 23,
            4: 20,
            3: 16,
            2: 12,
            1: 7,
            0: 0,
        }
        s = table.get(int(score_points), 0)
        return max(0, min(30, int(s)))

    if total_points <= 0:
        return 0

    sp = max(0, min(int(score_points), int(total_points)))
    eq_raw_11 = int(round(sp * 11.0 / float(total_points)))

    table_11 = {
        11: 30, 10: 29, 9: 28, 8: 27, 7: 26, 6: 25,
        5: 23, 4: 20, 3: 16, 2: 12, 1: 7, 0: 0,
    }
    s = table_11.get(eq_raw_11, 0)
    return max(0, min(30, int(s)))


def _grade_core(
    questions: List[Dict[str, Any]],
    answers: Optional[Dict[str, Any]] = None,
    correct_answers: Optional[Dict[str, Any]] = None,
    form: Any = None,
) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Internal grader:
      returns score_points, total_points, feedback_list
    """
    score_points = 0
    total_points = 0
    feedback: List[Dict[str, Any]] = []

    for q in questions:
        qid = str(q.get("id", "unknown"))
        prompt = q.get("prompt", "[No prompt provided]")
        qtype = (q.get("type") or "single").strip().lower()
        explanation = q.get("explanation", "") or ""

        user_ans = _get_user_answer_from_sources(qid=qid, answers=answers, form=form)
        correct_ans = _get_correct_answer(q, correct_answers=correct_answers)

        if qtype == "summary":
            pts, max_pts, ok = _score_summary_q10(user_ans, correct_ans)
        elif qtype == "single":
            pts, max_pts, ok = _score_single(user_ans, correct_ans)
        else:
            pts, max_pts, ok = _score_multi_exact(user_ans, correct_ans)

        score_points += pts
        total_points += max_pts

        feedback.append(
            {
                "qid": qid,
                "display_qid": _display_qid(qid),
                "prompt": prompt,
                "qtype": qtype,
                "user": sorted(list(set(user_ans))),
                "correct": sorted(list(set(correct_ans))),
                "ok": bool(ok),
                "points": int(pts),
                "max_points": int(max_pts),
                "explanation": explanation,
            }
        )

    return score_points, total_points, feedback


def grade(
    questions: List[Dict[str, Any]],
    form: Any = None,
    *,
    answers: Optional[Dict[str, Any]] = None,
    correct_answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Unified public API.

    Supports BOTH:
      - New result-page usage: grade(questions=..., answers=attempt_answers, correct_answers=correct_map)
      - Legacy usage: grade(questions, form)

    Returns a report dict for templates:
      {
        "score_points": int,
        "total_points": int,
        "scaled": int,
        "correct_count": int,
        "question_count": int,
        "feedback": [ ... ],
      }
    """
    score_points, total_points, feedback = _grade_core(
        questions=questions,
        answers=answers,
        correct_answers=correct_answers,
        form=form,
    )

    scaled = scale_reading_score(score_points, total_points)
    correct_count = sum(1 for x in feedback if x.get("ok"))
    question_count = len(feedback)

    return {
        "score_points": int(score_points),
        "total_points": int(total_points),
        "scaled": int(scaled),
        "correct_count": int(correct_count),
        "question_count": int(question_count),
        "feedback": feedback,
    }
