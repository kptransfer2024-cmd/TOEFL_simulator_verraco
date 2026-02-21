from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.sample_bank import SAMPLE_BANK
from services.exam_services import (
    create_attempt,
    duration_seconds,
    get_attempt,
    get_exam_set_for_attempt,
)
from services.grader import grade
from services.question_repo import normalize_question
from services.ai_tutor import tutor_answer_checked

router = APIRouter()
templates = Jinja2Templates(directory="templates")

LETTERS = ["A", "B", "C", "D", "E", "F"]


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _extract_answers_from_formdata(form) -> Dict[str, Any]:
    """
    Reads ans_<qid> fields from Starlette/FastAPI FormData.
    For radio: returns "A"
    For checkbox: returns ["A","C",...]
    IMPORTANT: Do NOT cast form to dict(), or multi-values will be lost.
    """
    out: Dict[str, Any] = {}

    try:
        keys = list(form.keys())
    except Exception:
        keys = []

    for k in keys:
        if not isinstance(k, str) or not k.startswith("ans_"):
            continue
        qid = k[len("ans_") :].strip()
        if not qid:
            continue

        try:
            vals = list(form.getlist(k))
        except Exception:
            v = form.get(k)
            vals = [v] if v is not None else []

        norm = [str(x).strip().upper() for x in vals if str(x).strip()]
        if not norm:
            continue

        out[qid] = norm[0] if len(norm) == 1 else norm

    return out


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _answer_keys_path() -> Path:
    return _project_root() / "data" / "answer_keys.json"


def _load_answer_keys() -> Dict[str, Any]:
    p = _answer_keys_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _normalize_correct_value(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip().upper() for x in v if str(x).strip()]

    s = str(v).strip().upper()
    if not s:
        return []

    s = s.replace(",", "").replace(" ", "")
    if len(s) == 1:
        return [s]

    if s.isdigit():
        out: List[str] = []
        for ch in s:
            i = int(ch)
            if 0 <= i < len(LETTERS):
                out.append(LETTERS[i])
        return out

    return [ch for ch in s if ch in LETTERS]


def _build_correct_answers(exam_set: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns {qid: "A" or ["A","C"]}

    Priority:
      1) data/answer_keys.json
         - list schema: [{"id": 1, "answers": ["B","D",...]}]
         - legacy dict schema: {"q1":"B", ...}
      2) fallback to question["correct"] in exam_set

    If choices were shuffled, and question meta contains:
      meta["old_to_new_letter"] = {"A":"C", "B":"A", ...}
    then we remap answer_keys letters into the shuffled letters.
    """
    keys = _load_answer_keys()
    out: Dict[str, Any] = {}

    questions = exam_set.get("questions", [])
    if not isinstance(questions, list):
        questions = []

    # Fast lookup for q object by its id
    q_by_id: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id", "")).strip()
        if qid:
            q_by_id[qid] = q

    def _extract_passage_no(exam_id: Any) -> Optional[int]:
        s = str(exam_id or "").strip()
        m = re.search(r"(\d+)", s)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    def _extract_qno(qid: str) -> Optional[int]:
        s = str(qid or "").strip()
        # Common patterns: "P11-Q03", "p11_q3", "11-3", "11-q3", "p11q03"
        m = re.search(r"(\d+)\s*[-_ ]\s*(?:Q|q)?\s*(\d+)$", s)
        if not m:
            m = re.search(r"[Pp]\s*(\d+)\s*[-_ ]?\s*[Qq]\s*(\d+)$", s)
        if not m:
            # last fallback: "...Q3" at the end
            m = re.search(r"(?:^|[^0-9])[Qq]\s*(\d+)$", s)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None
        try:
            return int(m.group(2))
        except Exception:
            return None

    def _get_old_to_new_map_for_qid(qid: str) -> Optional[dict]:
        q = q_by_id.get(qid)
        if not isinstance(q, dict):
            return None
        meta = q.get("meta")
        if not isinstance(meta, dict):
            return None
        m = meta.get("old_to_new_letter")
        return m if isinstance(m, dict) else None

    def _remap_if_shuffled(qid: str, val: Any) -> Any:
        """
        val is "A" or ["A","C"].
        If we have old_to_new_letter map, remap it.
        """
        m = _get_old_to_new_map_for_qid(qid)
        if not m:
            return val

        if isinstance(val, str):
            v = val.strip().upper()
            return m.get(v, v)

        if isinstance(val, list):
            remapped: List[str] = []
            for x in val:
                if not isinstance(x, str):
                    continue
                v = x.strip().upper()
                remapped.append(m.get(v, v))
            return remapped

        return val

    def _put(qid: str, raw_correct: Any) -> None:
        """
        Normalize + optional remap + write to out.
        """
        norm = _normalize_correct_value(raw_correct)
        if not norm:
            return

        val: Any = norm[0] if len(norm) == 1 else norm
        val = _remap_if_shuffled(qid, val)
        out[qid] = val

    # --- 1) Try list schema: [{"id": passage_no, "answers": [...]}] ---
    passage_no = _extract_passage_no(exam_set.get("id"))
    if passage_no is not None and isinstance(keys, list):
        row = None
        for r in keys:
            if not isinstance(r, dict):
                continue
            try:
                rid = int(r.get("id") or 0)
            except Exception:
                continue
            if rid == passage_no:
                row = r
                break

        answers = row.get("answers") if isinstance(row, dict) else None
        if isinstance(answers, list) and answers:
            for q in questions:
                if not isinstance(q, dict):
                    continue
                qid = str(q.get("id", "")).strip()
                if not qid:
                    continue
                qno = _extract_qno(qid)
                if not qno:
                    continue
                if 1 <= qno <= len(answers):
                    _put(qid, answers[qno - 1])

    # --- 2) Legacy dict schema: {"q1": "..."} ---
    if isinstance(keys, dict):
        for k, v in keys.items():
            if not isinstance(k, str):
                continue
            kk = k.strip()
            if kk.lower().startswith("q"):
                # In this schema, keys are directly qids like "q1".
                # We still support remap if qid matches a real question id.
                _put(kk, v)

    # --- 3) Fallback: embedded correct in exam_set (already shuffled correctly) ---
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id", "")).strip()
        if not qid:
            continue
        if qid in out:
            continue
        _put(qid, q.get("correct"))

    return out


def _get_question_by_qid(questions: List[Dict[str, Any]], qid: str) -> Optional[Dict[str, Any]]:
    qid_u = (qid or "").strip().upper()
    if not qid_u:
        return None
    for q in questions:
        if str(q.get("id", "")).strip().upper() == qid_u:
            return q
    return None


def _tutor_question_text(q: Dict[str, Any]) -> str:
    prompt = str(q.get("prompt", "")).strip()
    intro = str(q.get("intro", "")).strip() if q.get("intro") else ""
    choices = q.get("choices") or []

    lines: List[str] = []
    if intro:
        lines.append(intro)
        lines.append("")
    lines.append(prompt)

    if choices:
        lines.append("")
        for c in choices:
            try:
                letter = str(c[0]).strip().upper()
                text = str(c[1]).strip()
            except Exception:
                continue
            lines.append(f"{letter}. {text}")

    return "\n".join(lines).strip()


def _infer_mode_from_referer(request: Request) -> str:
    ref = request.headers.get("referer") or request.headers.get("referrer") or ""
    if not ref:
        return ""
    try:
        qs = parse_qs(urlparse(ref).query or "")
        return (qs.get("mode", [""])[0] or "").strip()
    except Exception:
        return ""


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    exam_set = SAMPLE_BANK[0]
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "title": exam_set.get("title", "Exam"),
            "default_minutes": exam_set.get("default_minutes", 18),
        },
    )


@router.post("/start")
def start(
    minutes: int = Form(...),
    mode: str = Form("full"),
    single_index: int = Form(1),
):
    attempt_id = create_attempt(minutes)

    attempt = get_attempt(attempt_id)
    if isinstance(attempt, dict):
        attempt["mode"] = (mode or "full").strip().lower()
        attempt["single_index"] = int(single_index or 1)

    if (mode or "").strip().lower() == "single":
        q = int(single_index or 1)
        return RedirectResponse(url=f"/exam/{attempt_id}?mode=single&q={q}", status_code=303)

    return RedirectResponse(url=f"/exam/{attempt_id}", status_code=303)


@router.post("/restart/{attempt_id}")
def restart(attempt_id: str):
    """
    Start a new attempt using the same minutes as the previous attempt if available.
    This matches result.html which posts to /restart/{attempt_id}.
    """
    attempt = get_attempt(attempt_id)
    minutes = 18
    if isinstance(attempt, dict):
        try:
            minutes = int(attempt.get("minutes") or minutes)
        except Exception:
            minutes = 18
    new_id = create_attempt(minutes)
    return RedirectResponse(url=f"/exam/{new_id}", status_code=303)


@router.get("/passage/{attempt_id}", response_class=HTMLResponse)
def passage(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    exam_set = get_exam_set_for_attempt(attempt_id)

    return templates.TemplateResponse(
        "passage.html",
        {
            "request": request,
            "attempt_id": attempt_id,

            "passage_title": exam_set.get("title", "Exam"),
            "passage_text": exam_set.get("passage", ""),

            "next_url": f"/exam/{attempt_id}?q=1",

            "started_at": attempt.get("started_at", 0),
            "duration_seconds": duration_seconds(attempt),
        },
    )



@router.get("/exam/{attempt_id}", response_class=HTMLResponse)
def exam(request: Request, attempt_id: str, q: int = 1, review: int = 0, mode: str = ""):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    exam_set = get_exam_set_for_attempt(attempt_id)
    raw_questions = exam_set.get("questions", [])
    questions = [normalize_question(x) for x in raw_questions]

    total = len(questions)
    idx = _clamp(int(q), 1, max(1, total))
    current = questions[idx - 1] if total else None

    review_mode = bool(review)
    correct_answers = _build_correct_answers(exam_set) if review_mode else {}

    saved_answers = attempt.get("answers", {}) or {}

    can_prev = idx > 1
    can_next = idx < total
    prev_index = idx - 1
    next_index = idx + 1
    is_last = idx == total

    context_passage = exam_set.get("passage", "") or ""
    context_question = _tutor_question_text(current) if current else ""

    ctx = {
        "request": request,
        "attempt_id": attempt_id,
        "title": exam_set.get("title", "Exam"),
        "passage": exam_set.get("passage", ""),
        "current_q": current,
        "total_questions": total,
        "current_index": idx,
        "can_prev": can_prev,
        "can_next": can_next,
        "prev_index": prev_index,
        "next_index": next_index,
        "is_last": is_last,
        "review_mode": review_mode,
        "mode": mode or "",
        "saved_answers": saved_answers,
        "correct_answers": correct_answers,
        "started_at": attempt.get("started_at", 0),
        "duration_seconds": duration_seconds(attempt),
        "context_passage": context_passage,
        "context_question": context_question,
    }
    return templates.TemplateResponse("exam.html", ctx)


@router.post("/exam/{attempt_id}/save")
async def save_and_nav(request: Request, attempt_id: str, target: int = Form(...)):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    updates = _extract_answers_from_formdata(form)
    if updates:
        attempt.setdefault("answers", {})
        if isinstance(attempt["answers"], dict):
            attempt["answers"].update(updates)

    mode = _infer_mode_from_referer(request)
    mode_q = f"&mode={mode}" if mode else ""
    return RedirectResponse(url=f"/exam/{attempt_id}?q={int(target)}{mode_q}", status_code=303)


@router.post("/exam/{attempt_id}/submit")
async def submit(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    updates = _extract_answers_from_formdata(form)
    if updates:
        attempt.setdefault("answers", {})
        if isinstance(attempt["answers"], dict):
            attempt["answers"].update(updates)

    return RedirectResponse(url=f"/result/{attempt_id}", status_code=303)


@router.post("/exam/{attempt_id}/autosubmit")
async def autosubmit(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    updates = _extract_answers_from_formdata(form)
    if updates:
        attempt.setdefault("answers", {})
        if isinstance(attempt["answers"], dict):
            attempt["answers"].update(updates)

    return RedirectResponse(url=f"/result/{attempt_id}", status_code=303)


@router.get("/result/{attempt_id}", response_class=HTMLResponse)
def result(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return RedirectResponse(url="/", status_code=303)

    exam_set = get_exam_set_for_attempt(attempt_id)

    raw_questions = exam_set.get("questions", [])
    questions_all = [normalize_question(x) for x in raw_questions]

    mode = str(attempt.get("mode") or "").strip().lower()
    single_index = int(attempt.get("single_index") or 1)

    if mode == "single" and questions_all:
        idx = _clamp(single_index, 1, len(questions_all))
        questions = [questions_all[idx - 1]]
    else:
        questions = questions_all

    correct_answers = _build_correct_answers(exam_set)

    report = grade(
        questions=questions,
        answers=attempt.get("answers", {}),
        correct_answers=correct_answers,
    )

    feedback = []
    scaled_score = None
    score_points = 0
    total_points = 0

    if isinstance(report, dict):
        feedback = report.get("feedback") or []
        scaled_score = report.get("scaled") if report.get("scaled") is not None else report.get("scaled_score")
        score_points = int(report.get("score_points") or 0)
        total_points = int(report.get("total_points") or 0)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "attempt_id": attempt_id,
            "title": exam_set.get("title", "Exam"),
            "report": report,
            "feedback": feedback,
            "scaled_score": scaled_score,
            "score_points": score_points,
            "total_points": total_points,
            "mode": mode,
            "single_index": single_index,
        },
    )


class TutorRequest(BaseModel):
    attempt_id: Optional[str] = None
    qid: Optional[str] = None
    passage: str = ""
    question: str = ""
    user_question: str = ""


@router.post("/tutor")
def tutor(req: TutorRequest):
    passage = req.passage or ""
    question = req.question or ""
    correct: Optional[Any] = None
    user_ans: Optional[Any] = None

    if req.attempt_id and req.qid:
        attempt = get_attempt(req.attempt_id)
        if attempt:
            exam_set = get_exam_set_for_attempt(req.attempt_id)
            correct_map = _build_correct_answers(exam_set)

            qid_u = str(req.qid).strip().upper()
            correct = correct_map.get(req.qid) or correct_map.get(qid_u)

            user_map = attempt.get("answers", {}) or {}
            user_ans = user_map.get(req.qid) or user_map.get(qid_u)

            if not passage:
                passage = exam_set.get("passage", "") or ""

            if not question:
                raw_questions = exam_set.get("questions", [])
                q_obj = _get_question_by_qid(raw_questions, qid_u)
                if q_obj:
                    question = _tutor_question_text(q_obj)

    data = tutor_answer_checked(
        passage=passage,
        question=question,
        user_question=req.user_question or "",
        correct_answer=correct,
        user_answer=user_ans,
    )
    return JSONResponse(data)
