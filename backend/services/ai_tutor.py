from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Union

from openai import OpenAI

_MODEL = os.getenv("TUTOR_MODEL", "deepseek-chat")
_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")

_RE_LETTER = re.compile(r"[A-F]")


def _as_list(v: Any) -> List[str]:
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
        # "012" -> A,B,C...
        out: List[str] = []
        letters = ["A", "B", "C", "D", "E", "F"]
        for ch in s:
            i = int(ch)
            if 0 <= i < len(letters):
                out.append(letters[i])
        return out
    return _RE_LETTER.findall(s)


def _client() -> OpenAI:
    if not _API_KEY:
        raise RuntimeError("Missing API key. Set DEEPSEEK_API_KEY or OPENAI_API_KEY.")
    return OpenAI(api_key=_API_KEY, base_url=_BASE_URL)


def _chat(messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 650) -> str:
    c = _client()
    resp = c.chat.completions.create(
        model=_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def tutor_answer_checked(
    *,
    passage: str,
    question: str,
    user_question: str,
    correct_answer: Optional[Union[str, List[str]]] = None,
    user_answer: Optional[Union[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Tutor with answer-key grounding when available.

    Behavior:
    - If correct_answer is provided: never claim a different correct option.
    - If the passage logic seems to disagree: explicitly say the answer key may be wrong and suggest verification.
    """
    ca = _as_list(correct_answer)
    ua = _as_list(user_answer)

    # A short "contract" for the model, so it does not contradict itself.
    header_lines: List[str] = []
    if ca:
        header_lines.append(f"Official correct answer: {', '.join(ca)}")
    if ua:
        header_lines.append(f"User selected: {', '.join(ua)}")
    header = "\n".join(header_lines).strip()

    system = (
        "You are an AI tutor for TOEFL Reading.\n"
        "Reply in the language of the user (defalut = ENGLISH) unless the user asks for a particular language.\n"
        "Use short paragraphs and cite evidence from the passage.\n"
        "Do not contradict the official answer key if it is provided.\n"
        "If the answer key conflicts with your reading, say: answer key may be wrong, and explain both sides.\n"
        "Avoid using dashes and quotation marks.\n"
        "IMPORTANT, particularly for sentence-insertion questions (typically question 9): The official answer letters (A-D) refer to the option labels, NOT the bracket markers [A]-[D] in the passage.\n"
        "For sentence-insertion questions, always restate the full text of the correct option (e.g., 'A = Insert at [B]') before explaining."
    )

    # If we have the key, ask the model to focus on explaining that key.
    if ca:
        user = (
            f"{header}\n\n"
            "Task:\n"
            "1) Carefully Restate and consicely Explain why the official correct answer is correct.\n"
            "2) If the user selected something else, explain why it is wrong.\n"
            "3) If multiple answers are correct, explain each briefly.\n\n"
            f"Passage:\n{passage}\n\n"
            f"Question:\n{question}\n\n"
            f"User question:\n{user_question}\n"
        )
        answer = _chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=700,
        )
        return {"ok": True, "answer": answer}

    # No key available. Provide best-effort tutoring without claiming certainty.
    user = (
        "Task:\n"
        "1) Answer the user question.\n"
        "2) If the user asks which option is correct, make your best guess but add a brief uncertainty note.\n\n"
        f"Passage:\n{passage}\n\n"
        f"Question:\n{question}\n\n"
        f"User question:\n{user_question}\n"
    )
    answer = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        max_tokens=700,
    )
    return {"ok": True, "answer": answer}


# Backward compatible alias if other code imports tutor_answer
def tutor_answer(passage: str, question: str, user_question: str) -> str:
    data = tutor_answer_checked(
        passage=passage,
        question=question,
        user_question=user_question,
        correct_answer=None,
        user_answer=None,
    )
    return str(data.get("answer", ""))
