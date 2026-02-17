from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.question_repo import normalize_question
from services.exam_services import (
    create_attempt,
    get_attempt,
    get_exam_set_for_attempt,
    duration_seconds,
)
from services.grader import grade, scale_reading_score
from core.sample_bank import SAMPLE_BANK

router = APIRouter()
templates = Jinja2Templates(directory="templates")

LETTERS = ["A", "B", "C", "D"]
_DEBUG = os.getenv("DEBUG_ROUTES", "").strip().lower() in {"1", "true", "yes", "y"}


def _dbg(*args) -> None:
    if _DEBUG:
        print("[DEBUG routes]", *args)


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _extract_answers_from_formdata(form) -> dict:
    """
    Reads ans_<qid> fields from a form post.
    Returns: {qid: "A"} or {qid: ["A","C"]}
    """
    answers: dict = {}

    items = []
    if hasattr(form, "multi_items"):
        items = list(form.multi_items())
    else:
        for k in form.keys():
            items.append((k, form.get(k)))

    by_key: dict = {}
    for k, v in items:
        if not isinstance(k, str) or not k.startswith("ans_"):
            continue
        by_key.setdefault(k, []).append(v)

    for key, vals in by_key.items():
        qid = key[4:]
        clean = [str(x).strip().upper() for x in vals if x is not None and str(x).strip() != ""]
        if not clean:
            continue
        answers[qid] = clean[0] if len(clean) == 1 else clean

    return answers


def _apply_page_answers(attempt: dict, current_qid: str, page_answers: dict) -> None:
    """
    Update attempt["answers"] with page_answers.
    If the current page has no selection for current_qid, delete its saved answer
    to avoid stale answers sticking around.
    """
    if not isinstance(attempt, dict):
        return

    answers = attempt.setdefault("answers", {})
    if not isinstance(answers, dict):
        answers = {}
        attempt["answers"] = answers

    qid = str(current_qid or "").strip()
    if not qid:
        if page_answers:
            answers.update(page_answers)
        return

    if page_answers and qid in page_answers:
        answers[qid] = page_answers[qid]
        return

    if qid in answers:
        del answers[qid]

    if page_answers:
        for k, v in page_answers.items():
            answers[k] = v


def _save_page_answers_from_form(attempt: dict, form) -> None:
    """
    One place to persist page answers for save/submit/autosubmit.
    Requires exam.html to include:
      <input type="hidden" name="_current_qid" value="{{ q.id }}">
    """
    page_answers = _extract_answers_from_formdata(form)
    current_qid = str(form.get("_current_qid") or "").strip()
    _apply_page_answers(attempt, current_qid, page_answers)


def _get_seq(q: dict) -> int:
    meta = q.get("meta") if isinstance(q.get("meta"), dict) else {}
    try:
        return int(meta.get("seq") or 0)
    except Exception:
        return 0


def _ensure_seq(questions: list[dict]) -> list[dict]:
    """
    Ensure every question has meta.seq = 1..N (if missing).
    This keeps your existing navigation logic stable.
    """
    out: list[dict] = []
    for i, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            continue
        qq = dict(q)
        meta = qq.get("meta") if isinstance(qq.get("meta"), dict) else {}
        if not meta.get("seq"):
            meta = dict(meta)
            meta["seq"] = i
            qq["meta"] = meta
        out.append(qq)
    return out


def _find_question_by_seq(questions: list, seq: int) -> dict | None:
    for q in questions:
        if not isinstance(q, dict):
            continue
        if _get_seq(q) == int(seq):
            return q
    return None


def _normalize_questions(raw_questions: list) -> list[dict]:
    """
    Normalize every question for template rendering:
      - prompt always exists (mapped from stem)
      - choices become [[A,text],[B,text]...]
      - type field present ("single"/"multi"/summary"...)
    NOTE: normalize_question() may or may not preserve correct_*, so we also
          keep raw fields accessible for answer extraction.
    """
    normalized: list[dict] = []
    if not isinstance(raw_questions, list):
        return normalized

    for q in raw_questions:
        if not isinstance(q, dict):
            continue
        nq = normalize_question(q)
        meta = nq.get("meta") if isinstance(nq.get("meta"), dict) else {}
        meta = dict(meta)
        meta["_raw"] = q
        nq["meta"] = meta
        normalized.append(nq)

    return _ensure_seq(normalized)


# ------------------------------
# Correct answer loader (answer_keys.json)
# ------------------------------
@lru_cache(maxsize=1)
def _load_answer_keys() -> dict:
    """
    Loads ./data/answer_keys.json (a list) and flattens into a dict:
      - "20-7" -> "A" or ["A","C"]
      - "20-07" -> ...
      - "P20-Q07" -> ...
      - "P20-Q7" -> ...
    """
    p = Path(__file__).resolve().parents[1] / "data" / "answer_keys.json"
    if not p.exists():
        return {}

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(data, list):
        return {}

    out: dict = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        ans = item.get("answers")
        if pid is None or not isinstance(ans, list):
            continue

        try:
            pid_i = int(pid)
        except Exception:
            continue

        for i, a in enumerate(ans, start=1):
            if a is None:
                continue
            s = str(a).strip().upper()
            if not s:
                continue
            v = s if len(s) == 1 else list(s)

            out[f"{pid_i}-{i}".upper()] = v
            out[f"{pid_i:02d}-{i}".upper()] = v
            out[f"P{pid_i}-Q{i:02d}".upper()] = v
            out[f"P{pid_i}-Q{i}".upper()] = v

    return out


def _to_letter_from_index(idx) -> str | None:
    try:
        i = int(idx)
    except Exception:
        return None
    if 0 <= i < len(LETTERS):
        return LETTERS[i]
    return None


def _norm_qid(qid: str) -> str:
    return (qid or "").strip().upper()


def _extract_correct_from_any(q: dict) -> str | list[str] | None:
    if not isinstance(q, dict):
        return None

    for k in ("correct_letter", "answer", "correct"):
        v = q.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()

    if "correct_index" in q:
        letter = _to_letter_from_index(q.get("correct_index"))
        if letter:
            return letter

    for k in ("correct_letters", "correct_indices", "answers"):
        v = q.get(k)
        if isinstance(v, list) and v:
            out: list[str] = []
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip().upper())
                else:
                    letter = _to_letter_from_index(item)
                    if letter:
                        out.append(letter)
            return out if out else None

    meta = q.get("meta") if isinstance(q.get("meta"), dict) else {}
    for k in ("correct_letter", "answer", "correct"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()

    if "correct_index" in meta:
        letter = _to_letter_from_index(meta.get("correct_index"))
        if letter:
            return letter

    for k in ("correct_letters", "correct_indices", "answers"):
        v = meta.get(k)
        if isinstance(v, list) and v:
            out: list[str] = []
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip().upper())
                else:
                    letter = _to_letter_from_index(item)
                    if letter:
                        out.append(letter)
            return out if out else None

    raw = meta.get("_raw") if isinstance(meta.get("_raw"), dict) else {}
    if isinstance(raw, dict):
        for k in ("correct_letter", "answer", "correct"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().upper()

        if "correct_index" in raw:
            letter = _to_letter_from_index(raw.get("correct_index"))
            if letter:
                return letter

        for k in ("correct_letters", "correct_indices", "answers"):
            v = raw.get(k)
            if isinstance(v, list) and v:
                out: list[str] = []
                for item in v:
                    if isinstance(item, str) and item.strip():
                        out.append(item.strip().upper())
                    else:
                        letter = _to_letter_from_index(item)
                        if letter:
                            out.append(letter)
                return out if out else None

        raw_meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        if isinstance(raw_meta, dict):
            for k in ("correct_letter", "answer", "correct"):
                v = raw_meta.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip().upper()
            if "correct_index" in raw_meta:
                letter = _to_letter_from_index(raw_meta.get("correct_index"))
                if letter:
                    return letter

    return None


_QID_RE = re.compile(
    r"^(?:P(?P<pid>\d{1,2})-Q(?P<q>\d{1,2})|(?P<pid2>\d{1,2})-(?P<q2>\d{1,2}))$",
    re.I,
)


def _lookup_correct_from_answer_keys(qid: str) -> str | list[str] | None:
    keys = _load_answer_keys()
    if not keys or not qid:
        return None

    qid_n = _norm_qid(qid)

    v = keys.get(qid_n)
    if v is not None:
        return v

    m = _QID_RE.match(qid_n)
    if not m:
        return None

    pid = m.group("pid") or m.group("pid2")
    qn = m.group("q") or m.group("q2")
    try:
        pid_i = int(pid)
        q_i = int(qn)
    except Exception:
        return None

    for k in (
        f"{pid_i}-{q_i}",
        f"{pid_i:02d}-{q_i}",
        f"P{pid_i}-Q{q_i:02d}",
        f"P{pid_i}-Q{q_i}",
    ):
        vv = keys.get(k.upper())
        if vv is not None:
            return vv

    return None


def _build_correct_answers(questions: list[dict]) -> dict:
    out: dict = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = q.get("id")
        if not isinstance(qid, str) or not qid.strip():
            continue
        qid_n = _norm_qid(qid)

        ca = _extract_correct_from_any(q)
        if ca is None:
            ca = _lookup_correct_from_answer_keys(qid_n)

        if isinstance(ca, str) and ca.strip():
            val = ca.strip().upper()
            out[qid_n] = val
            out[qid] = val
        elif isinstance(ca, list) and ca:
            val_list = [str(x).strip().upper() for x in ca if str(x).strip()]
            if val_list:
                out[qid_n] = val_list
                out[qid] = val_list

    return out


def _ensure_full_set_for_single(attempt: dict, exam_set: dict) -> dict:
    """
    Step A: single mode must use the full exam set (1-10).
    If exam_services returns a trimmed set, fallback to SAMPLE_BANK[0].
    """
    mode = (attempt.get("mode") or "full").strip().lower()
    if mode != "single":
        return exam_set

    raw_qs = exam_set.get("questions", [])
    if not isinstance(raw_qs, list) or len(raw_qs) < 10:
        _dbg(
            "single-mode exam_set seems trimmed, fallback to SAMPLE_BANK[0].",
            "got_len=",
            (len(raw_qs) if isinstance(raw_qs, list) else None),
        )
        return SAMPLE_BANK[0]

    return exam_set


# ------------------------------
# Routes
# ------------------------------
@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    exam_set = SAMPLE_BANK[0]
    _dbg("HOME bank questions =", len(exam_set.get("questions", [])))
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "title": exam_set["title"], "default_minutes": exam_set["default_minutes"]},
    )


@router.post("/start")
def start(minutes: int = Form(...), mode: str = Form("full"), single_index: int = Form(1)):
    mode = (mode or "full").strip().lower()
    if mode not in {"full", "single"}:
        mode = "full"

    try:
        single_index = int(single_index)
    except Exception:
        single_index = 1

    attempt_id = create_attempt(minutes, mode=mode, single_index=single_index)

    if mode == "single":
        return RedirectResponse(url=f"/exam/{attempt_id}?q={single_index}", status_code=303)

    return RedirectResponse(url=f"/passage/{attempt_id}", status_code=303)


@router.get("/passage/{attempt_id}", response_class=HTMLResponse)
def passage(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    exam_set = get_exam_set_for_attempt(attempt)
    exam_set = _ensure_full_set_for_single(attempt, exam_set)

    raw_qs = exam_set.get("questions", [])
    _dbg("PASSAGE exam_set title =", exam_set.get("title"))
    _dbg("PASSAGE questions count =", len(raw_qs) if isinstance(raw_qs, list) else "N/A")
    if isinstance(raw_qs, list) and raw_qs:
        _dbg("PASSAGE first qid/type =", raw_qs[0].get("id"), raw_qs[0].get("type"))
        _dbg("PASSAGE last  qid/type =", raw_qs[-1].get("id"), raw_qs[-1].get("type"))

    p = exam_set.get("passage", "")
    passage_title = ""
    passage_text = ""

    if isinstance(p, dict):
        passage_title = str(p.get("title") or "").strip()
        passage_text = str(p.get("text") or p.get("content") or "").strip()
        if not passage_text:
            passage_text = str(p).strip()
    else:
        passage_text = str(p or "").strip()

    try:
        started_at = int(attempt.get("started_at") or 0)
    except Exception:
        started_at = 0

    dur = duration_seconds(attempt)
    try:
        dur = int(dur)
    except Exception:
        dur = 0

    ctx = {
        "request": request,
        "attempt_id": attempt_id,
        "title": exam_set.get("title", "Passage"),
        "passage_title": passage_title or exam_set.get("title", "Passage"),
        "passage_text": passage_text,
        "duration_seconds": dur,
        "started_at": started_at,
        "next_url": f"/exam/{attempt_id}?q=1",
    }
    return templates.TemplateResponse("passage.html", ctx)


@router.get("/exam/{attempt_id}", response_class=HTMLResponse)
def exam(request: Request, attempt_id: str, q: int = 1, review: int = 0):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    review_mode = bool(review)

    exam_set = get_exam_set_for_attempt(attempt)
    exam_set = _ensure_full_set_for_single(attempt, exam_set)

    raw_qs = exam_set.get("questions", [])
    all_qs = _normalize_questions(raw_qs)
    total_q = len(all_qs)

    _dbg("EXAM total normalized questions =", total_q)

    if total_q <= 0:
        return HTMLResponse("No questions available", status_code=500)

    mode = (attempt.get("mode") or "full").lower().strip()
    if mode not in {"full", "single"}:
        mode = "full"

    # Keep the original q for redirect normalization (only meaningful in full mode).
    q_requested = q

    if mode == "single":
        try:
            cur_seq = int(attempt.get("single_index") or 1)
        except Exception:
            cur_seq = 1
    else:
        try:
            cur_seq = int(q_requested)
        except Exception:
            cur_seq = 1

    cur_seq = _clamp(cur_seq, 1, total_q)

    # ---- FIX: prevent infinite "next" URL growth ----
    # If user asks q beyond range, redirect to the canonical URL.
    if mode == "full":
        try:
            q_req_i = int(q_requested)
        except Exception:
            q_req_i = 1
        if q_req_i != cur_seq:
            return RedirectResponse(
                url=f"/exam/{attempt_id}?q={cur_seq}&review={1 if review_mode else 0}",
                status_code=303,
            )
    # -----------------------------------------------

    cur_q = _find_question_by_seq(all_qs, cur_seq) or all_qs[cur_seq - 1]

    _dbg("EXAM current seq =", cur_seq, "qid/type =", cur_q.get("id"), cur_q.get("type"))

    correct_answers = _build_correct_answers(all_qs) if review_mode else {}

    try:
        started_at = int(attempt.get("started_at") or 0)
    except Exception:
        started_at = 0

    dur = duration_seconds(attempt)
    try:
        dur = int(dur)
    except Exception:
        dur = 0

    ctx = {
        "request": request,
        "attempt_id": attempt_id,
        "title": exam_set.get("title", "Exam"),
        "passage": exam_set.get("passage", ""),
        "questions": all_qs,
        "current_q": cur_q,
        "current_index": cur_seq,
        "total_questions": total_q,
        "mode": mode,
        "duration_seconds": dur,
        "started_at": started_at,
        "review_mode": review_mode,
        "saved_answers": attempt.get("answers", {}),
        "result": attempt.get("result"),
        "correct_answers": correct_answers,
        "can_prev": (mode == "full" and cur_seq > 1),
        "can_next": (mode == "full" and cur_seq < total_q),
        "prev_index": _clamp(cur_seq - 1, 1, total_q),
        "next_index": _clamp(cur_seq + 1, 1, total_q),
        "is_last": (mode == "full" and cur_seq == total_q),
    }

    return templates.TemplateResponse("exam.html", ctx)


@router.post("/exam/{attempt_id}/save")
async def save_and_nav(request: Request, attempt_id: str, target: int = Form(...)):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    form = await request.form()
    _save_page_answers_from_form(attempt, form)

    exam_set = get_exam_set_for_attempt(attempt)
    exam_set = _ensure_full_set_for_single(attempt, exam_set)

    all_qs = _normalize_questions(exam_set.get("questions", []))
    total_q = len(all_qs)
    if total_q <= 0:
        return HTMLResponse("No questions available", status_code=500)

    try:
        target_i = int(target)
    except Exception:
        target_i = 1
    target_i = _clamp(target_i, 1, total_q)

    return RedirectResponse(url=f"/exam/{attempt_id}?q={target_i}", status_code=303)


@router.post("/exam/{attempt_id}/submit")
async def submit(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    form = await request.form()
    exam_set = get_exam_set_for_attempt(attempt)
    exam_set = _ensure_full_set_for_single(attempt, exam_set)

    _save_page_answers_from_form(attempt, form)

    mode = (attempt.get("mode") or "full").lower().strip()
    if mode not in {"full", "single"}:
        mode = "full"

    class _FormAdapter:
        def __init__(self, answers: dict):
            self.answers = answers

        def getlist(self, key: str):
            if not key.startswith("ans_"):
                return []
            qid = key[4:]
            v = self.answers.get(qid)
            if v is None:
                return []
            if isinstance(v, list):
                return v
            return [v]

        def get(self, key: str, default=None):
            vals = self.getlist(key)
            return vals[0] if vals else default

    fake_form = _FormAdapter(attempt.get("answers", {}))
    questions_all = _normalize_questions(exam_set.get("questions", []))

    if mode == "single":
        try:
            seq = int(attempt.get("single_index") or 1)
        except Exception:
            seq = 1
        seq = _clamp(seq, 1, len(questions_all) if questions_all else 1)
        q_one = _find_question_by_seq(questions_all, seq) or questions_all[seq - 1]
        grade_questions = [q_one] if q_one else []
    else:
        grade_questions = questions_all

    score, total, feedback = grade(grade_questions, fake_form)
    scaled_score = scale_reading_score(score, total)

    attempt["submitted"] = True
    attempt["timed_out"] = False
    attempt["result"] = {
        "score": score,
        "total": total,
        "feedback": feedback,
        "scaled_score": scaled_score,
    }

    return RedirectResponse(url=f"/result/{attempt_id}", status_code=303)


@router.post("/exam/{attempt_id}/autosubmit")
async def autosubmit(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    form = await request.form()
    exam_set = get_exam_set_for_attempt(attempt)
    exam_set = _ensure_full_set_for_single(attempt, exam_set)

    _save_page_answers_from_form(attempt, form)

    mode = (attempt.get("mode") or "full").lower().strip()
    if mode not in {"full", "single"}:
        mode = "full"

    class _FormAdapter:
        def __init__(self, answers: dict):
            self.answers = answers

        def getlist(self, key: str):
            if not key.startswith("ans_"):
                return []
            qid = key[4:]
            v = self.answers.get(qid)
            if v is None:
                return []
            if isinstance(v, list):
                return v
            return [v]

        def get(self, key: str, default=None):
            vals = self.getlist(key)
            return vals[0] if vals else default

    fake_form = _FormAdapter(attempt.get("answers", {}))
    questions_all = _normalize_questions(exam_set.get("questions", []))

    if mode == "single":
        try:
            seq = int(attempt.get("single_index") or 1)
        except Exception:
            seq = 1
        seq = _clamp(seq, 1, len(questions_all) if questions_all else 1)
        q_one = _find_question_by_seq(questions_all, seq) or questions_all[seq - 1]
        grade_questions = [q_one] if q_one else []
    else:
        grade_questions = questions_all

    score, total, feedback = grade(grade_questions, fake_form)
    scaled_score = scale_reading_score(score, total)

    attempt["submitted"] = True
    attempt["timed_out"] = True
    attempt["result"] = {
        "score": score,
        "total": total,
        "feedback": feedback,
        "scaled_score": scaled_score,
    }

    return RedirectResponse(url=f"/timeup/{attempt_id}", status_code=303)


@router.get("/timeup/{attempt_id}", response_class=HTMLResponse)
def timeup(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt or not attempt["submitted"] or not attempt.get("timed_out"):
        return HTMLResponse("Time-up page not available", status_code=404)

    res = attempt["result"]
    return templates.TemplateResponse(
        "timeup.html",
        {
            "request": request,
            "attempt_id": attempt_id,
            "score": res["score"],
            "total": res["total"],
            "scaled_score": res.get("scaled_score"),
        },
    )


@router.post("/restart/{attempt_id}")
def restart(attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    try:
        minutes = int(attempt.get("minutes") or 20)
    except Exception:
        minutes = 20

    mode = (attempt.get("mode") or "full").strip().lower()
    if mode not in {"full", "single"}:
        mode = "full"

    try:
        single_index = int(attempt.get("single_index") or 1)
    except Exception:
        single_index = 1

    new_attempt_id = create_attempt(minutes, mode=mode, single_index=single_index)

    if mode == "single":
        return RedirectResponse(url=f"/exam/{new_attempt_id}?q={single_index}", status_code=303)

    return RedirectResponse(url=f"/passage/{new_attempt_id}", status_code=303)


@router.get("/result/{attempt_id}", response_class=HTMLResponse)
def result(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt or not attempt["submitted"]:
        return HTMLResponse("Result not found (not submitted yet?)", status_code=404)

    res = attempt["result"]
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "attempt_id": attempt_id,
            "score": res["score"],
            "total": res["total"],
            "feedback": res["feedback"],
            "scaled_score": res.get("scaled_score"),
        },
    )
