from __future__ import annotations
from copy import deepcopy
import random
from typing import Any, Dict, List, Optional, Tuple

Choice = Tuple[str, str]  # ("A", "text")

def _relabel_choices(choice_texts: List[str]) -> List[Choice]:
    labels = [chr(ord("A") + i) for i in range(len(choice_texts))]
    return list(zip(labels, choice_texts))

def shuffle_exam_set(exam_set: Dict[str, Any], seed: Optional[int] = None) -> Dict[str, Any]:
    rng = random.Random(seed)
    data = deepcopy(exam_set)

    for q in data.get("questions", []):
        choices: List[Choice] = q.get("choices", [])
        correct_letters: List[str] = q.get("correct", [])

        if not choices or not correct_letters:
            continue

        letter_to_text = {letter: text for (letter, text) in choices}
        correct_texts = [letter_to_text[c] for c in correct_letters if c in letter_to_text]

        texts = [text for (_, text) in choices]
        rng.shuffle(texts)

        new_choices = _relabel_choices(texts)
        text_to_new_letter = {text: letter for (letter, text) in new_choices}
        new_correct = [text_to_new_letter[t] for t in correct_texts if t in text_to_new_letter]

        q["choices"] = new_choices
        q["correct"] = new_correct

    return data

