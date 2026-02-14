from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.exam_services import (
    create_attempt,
    get_attempt,
    get_exam_set_for_attempt,
    duration_seconds,
)
from services.grader import grade
from core.sample_bank import SAMPLE_BANK

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _extract_answers_from_form(questions: list, form) -> dict:
    """
    Extract answers in the same shape the HTML form uses:
      name="ans_<question_id>", value="A|B|C|D"
    Returns: {question_id: "A"|"B"|"C"|"D"}
    """
    answers: dict = {}
    for q in questions:
        qid = q.get("id")
        if not qid:
            continue

        # IMPORTANT: must match exam.html: name="ans_{{ q.id }}"
        field = f"ans_{qid}"

        # For radio: one value; for checkbox: may be multiple values
        # Starlette FormData supports getlist()
        if hasattr(form, "getlist"):
            vals = form.getlist(field)
            if not vals:
                continue
            if len(vals) == 1:
                answers[str(qid)] = str(vals[0]).strip().upper()
            else:
                answers[str(qid)] = [str(v).strip().upper() for v in vals if v]
        else:
            val = form.get(field)
            if val:
                answers[str(qid)] = str(val).strip().upper()

    return answers

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    exam_set = SAMPLE_BANK[0]
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "title": exam_set["title"], "default_minutes": exam_set["default_minutes"]},
    )


@router.post("/start")
def start(minutes: int = Form(...)):
    attempt_id = create_attempt(minutes)
    return RedirectResponse(url=f"/exam/{attempt_id}", status_code=303)


@router.get("/exam/{attempt_id}", response_class=HTMLResponse)
def exam(request: Request, attempt_id: str, review: int = 0):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    exam_set = get_exam_set_for_attempt(attempt)

    return templates.TemplateResponse(
        "exam.html",
        {
            "request": request,
            "attempt_id": attempt_id,
            "title": exam_set["title"],
            "passage": exam_set["passage"],
            "questions": exam_set["questions"],
            "duration_seconds": duration_seconds(attempt),
            "started_at": attempt["started_at"],
            # Review support (used by exam.html to pre-check and optionally disable inputs)
            "review_mode": bool(review),
            "saved_answers": attempt.get("answers", {}),
            "result": attempt.get("result"),
        },
    )


@router.post("/exam/{attempt_id}/submit")
async def submit(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    form = await request.form()

    # Use the SAME shuffled exam_set for grading (deterministic with seed)
    exam_set = get_exam_set_for_attempt(attempt)

    # Persist answers for review page
    attempt["answers"] = _extract_answers_from_form(exam_set["questions"], form)

    score, total, feedback = grade(exam_set["questions"], form)

    attempt["submitted"] = True
    attempt["timed_out"] = False
    attempt["result"] = {"score": score, "total": total, "feedback": feedback}

    return RedirectResponse(url=f"/result/{attempt_id}", status_code=303)


@router.post("/exam/{attempt_id}/autosubmit")
async def autosubmit(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)

    form = await request.form()

    # Use the SAME shuffled exam_set for grading (deterministic with seed)
    exam_set = get_exam_set_for_attempt(attempt)

    # Persist answers for review page
    attempt["answers"] = _extract_answers_from_form(exam_set["questions"], form)

    score, total, feedback = grade(exam_set["questions"], form)

    attempt["submitted"] = True
    attempt["timed_out"] = True
    attempt["result"] = {"score": score, "total": total, "feedback": feedback}

    return RedirectResponse(url=f"/timeup/{attempt_id}", status_code=303)


@router.get("/timeup/{attempt_id}", response_class=HTMLResponse)
def timeup(request: Request, attempt_id: str):
    attempt = get_attempt(attempt_id)
    if not attempt or not attempt["submitted"] or not attempt.get("timed_out"):
        return HTMLResponse("Time-up page not available", status_code=404)

    res = attempt["result"]
    return templates.TemplateResponse(
        "timeup.html",
        {"request": request, "attempt_id": attempt_id, "score": res["score"], "total": res["total"]},
    )


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
        },
    )
