from typing import Any, List, Dict, Tuple

def grade(questions: List[Dict[str, Any]], form: Any) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Grades user answers with high robustness and efficiency.
    
    Args:
        questions: List of question dictionaries from the database.
        form: The request form object (supporting .getlist() or dict-like access).
        
    Returns:
        A tuple of (score, total, feedback_list).
    """
    score = 0
    total = len(questions)
    feedback: List[Dict[str, Any]] = []

    for q in questions:
        # Use .get() to prevent crashes if keys are missing
        qid = q.get("id", "unknown")
        prompt = q.get("prompt", "[No prompt provided]")
        qtype = q.get("type", "multiple-choice")
        explanation = q.get("explanation", "")
        
        # Expected key in HTML form: e.g., "ans_01_q1"
        # Adjust the key format to match your frontend requirement
        input_key = f"ans_{qid}"
        
        # 1. Normalize User Input
        if hasattr(form, "getlist"):
            raw_user = form.getlist(input_key)
        else:
            val = form.get(input_key, [])
            raw_user = val if isinstance(val, list) else [val]
            
        user_ans = sorted([str(a).strip().upper() for a in raw_user if a])

        # 2. Normalize Correct Answer
        raw_correct = q.get("correct", [])
        if isinstance(raw_correct, str):
            raw_correct = [raw_correct]
        correct_ans = sorted([str(a).strip().upper() for a in raw_correct if a])

        # 3. Validation Logic
        is_ok = (user_ans == correct_ans) and len(correct_ans) > 0
        
        if is_ok:
            score += 1

        feedback.append({
            "qid": qid,
            "prompt": prompt,
            "qtype": qtype,
            "user": user_ans,
            "correct": correct_ans,
            "ok": is_ok,
            "explanation": explanation
        })

    return score, total, feedback