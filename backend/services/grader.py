from __future__ import annotations

from typing import Any, List, Dict, Tuple
import re

# support many qid styles:
#   P11-Q10, p11_q10, p11-q10, P11Q10, 11-10, 11_q10, 11-q10
_RE_PATTERNS = [
    re.compile(r"^P(?P<pid>\d+)[-_]?Q(?P<qn>\d+)$", re.IGNORECASE),       # P11-Q10 / P11_Q10 / P11Q10
    re.compile(r"^P(?P<pid>\d+)[-_]?(?:Q|q)(?P<qn>\d+)$", re.IGNORECASE), # extra tolerant
    re.compile(r"^(?P<pid>\d+)[-_](?P<qn>\d+)$", re.IGNORECASE),          # 11-10 / 11_10
    re.compile(r"^(?P<pid>\d+)[-_]q(?P<qn>\d+)$", re.IGNORECASE),         # 11-q10
    re.compile(r"^p(?P<pid>\d+)[-_]?q(?P<qn>\d+)$", re.IGNORECASE),       # p11_q10 / p11-q10
    re.compile(r"^p(?P<pid>\d+)[-_]?(?P<qn>\d+)$", re.IGNORECASE),        # p11-10 / p11_10
]


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


def _get_form_list(form: Any, key: str) -> List[str]:
    """
    Robustly get list values from a form-like object.
    Supports:
      - Starlette FormData: form.getlist(key)
      - Dict-like: form.get(key)
    """
    if hasattr(form, "getlist"):
        raw = form.getlist(key)
    else:
        v = form.get(key, [])
        raw = v if isinstance(v, list) else [v]

    out: List[str] = []
    for a in raw:
        if a is None:
            continue
        s = str(a).strip().upper()
        if s:
            out.append(s)
    return out


def _normalize_correct(q: Dict[str, Any]) -> List[str]:
    """
    Normalize correct answers from question dict.
    Accepts:
      - correct: "A" or ["A","C"] or "ABC"
      - correct_letter / correct_letters
    Returns uppercase list (deduped, sorted).
    """
    raw = q.get("correct")

    if raw is None:
        raw = q.get("correct_letters") or q.get("correct_letter")

    if raw is None:
        return []

    # Key fix:
    # If correct is like "ABC" or "AEF", split into letters for multi select.
    if isinstance(raw, str):
        s = raw.strip().upper()
        if re.fullmatch(r"[A-F]{2,}", s):
            raw_list = list(s)
        else:
            raw_list = [s]
    elif isinstance(raw, list):
        raw_list = raw
    else:
        raw_list = [raw]

    out: List[str] = []
    for x in raw_list:
        if x is None:
            continue
        s = str(x).strip().upper()
        if s:
            out.append(s)

    return sorted(list(set(out)))


def _score_single(user: List[str], correct: List[str]) -> Tuple[int, int, bool]:
    """
    Single-choice scoring:
      full match => 1 point
      else => 0
    """
    max_points = 1
    if not correct:
        return 0, max_points, False
    if len(user) != 1:
        return 0, max_points, False
    ok = (user[0] == correct[0]) if len(correct) == 1 else (user[0] in correct)
    return (1 if ok else 0), max_points, ok


def _score_multi_exact(user: List[str], correct: List[str]) -> Tuple[int, int, bool]:
    """
    Multi-answer (non-summary) scoring:
      exact set match => 1 point
      else => 0
    This keeps 1-9 behavior stable if you ever have multi outside Q10.
    """
    max_points = 1
    if not correct:
        return 0, max_points, False
    ok = (sorted(set(user)) == sorted(set(correct))) and len(user) > 0
    return (1 if ok else 0), max_points, ok


def _score_summary_q10(user: List[str], correct: List[str]) -> Tuple[int, int, bool]:
    """
    Q10 scoring (summary):
      - full correct => 3
      - partial correct (subset, no wrong selections, at least 1 selected) => 2
      - any wrong selection => 0
      - blank => 0
    """
    max_points = 3
    if not correct:
        return 0, max_points, False

    u_set = set(user)
    c_set = set(correct)

    if len(u_set) == 0:
        return 0, max_points, False

    if not u_set.issubset(c_set):
        return 0, max_points, False

    if u_set == c_set:
        return 3, max_points, True

    return 2, max_points, False


def grade(questions: List[Dict[str, Any]], form: Any) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Grades user answers.
    Returns:
      score_points, total_points, feedback_list
    """
    score_points = 0
    total_points = 0
    feedback: List[Dict[str, Any]] = []

    for q in questions:
        qid = q.get("id", "unknown")
        prompt = q.get("prompt", "[No prompt provided]")
        qtype = (q.get("type") or "single").strip().lower()
        explanation = q.get("explanation", "")

        input_key = f"ans_{qid}"

        user_ans = _get_form_list(form, input_key)
        correct_ans = _normalize_correct(q)

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
                "prompt": prompt,
                "qtype": qtype,
                "user": sorted(list(set(user_ans))),
                "correct": sorted(list(set(correct_ans))),
                "ok": bool(ok),
                "points": int(pts),
                "max_points": int(max_pts),
                "explanation": explanation,
                "display_qid": _display_qid(qid),
            }
        )

    return score_points, total_points, feedback
