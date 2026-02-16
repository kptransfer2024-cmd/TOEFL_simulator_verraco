from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF


ROOT = Path(__file__).resolve().parents[1]  # backend/
PDF_PATH = ROOT / "data" / "ql2.pdf"
OUT_PATH = ROOT / "data" / "q10_bank.json"


PASSAGE_HEADER_RE = re.compile(r"(?m)^\s*Passage\s+(\d{1,3})\s*[-–—]\s*(.+?)\s*$")
Q10_START_RE = re.compile(r"(?m)^\s*10\.\s*")

# Remove invisible junk: zero-width spaces, BOM, NBSP
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_NBSP = re.compile(r"\u00a0")

ANSWER_CHOICES_SPLIT_RE = re.compile(r"(?im)^\s*Answer\s+Choices\s*$")

BULLET_LINE_RE = re.compile(r"^\s*([·●•\?]+)\s*$")

OPT_START_RE = re.compile(r"(?m)^\s*([A-F])[\u200b\s]*[.)：:—–-]\s*")


def clean_text(s: str) -> str:
    s = _ZERO_WIDTH.sub("", s)
    s = _NBSP.sub(" ", s)
    return s


def norm_space(s: str) -> str:
    s = clean_text(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def read_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    parts: List[str] = []
    for i in range(doc.page_count):
        parts.append(doc.load_page(i).get_text("text"))
    return clean_text("\n".join(parts))


def split_passages(full_text: str) -> List[Tuple[int, str, str]]:
    hits = list(PASSAGE_HEADER_RE.finditer(full_text))
    out: List[Tuple[int, str, str]] = []
    for idx, m in enumerate(hits):
        pno = int(m.group(1))
        title = m.group(2).strip()
        a = m.start()
        b = hits[idx + 1].start() if idx + 1 < len(hits) else len(full_text)
        out.append((pno, title, full_text[a:b]))
    return out


def extract_q10_block(passage_block: str) -> Optional[str]:
    m = Q10_START_RE.search(passage_block)
    if not m:
        return None
    return passage_block[m.start():].strip()


def parse_q10(q10_block: str, passage_no: int, debug: bool = False) -> Optional[Dict]:
    q10_clean = clean_text(q10_block)

    parts = ANSWER_CHOICES_SPLIT_RE.split(q10_clean, maxsplit=1)
    if len(parts) != 2:
        return None

    before_text = parts[0].strip()
    after_text = parts[1].strip()

    before_lines = [ln.strip() for ln in before_text.splitlines() if ln.strip()]
    before_lines = [ln for ln in before_lines if not BULLET_LINE_RE.match(ln)]

    if len(before_lines) < 2:
        return None
    intro = norm_space(before_lines[-1])
    prompt = norm_space(" ".join(before_lines[:-1]))

    matches = list(OPT_START_RE.finditer(after_text))
    if debug:
        print(f"[DEBUG] Passage {passage_no} option markers found: {len(matches)}")

    if len(matches) < 3:
        return None

    choices: List[Dict[str, str]] = []
    for i, m in enumerate(matches):
        letter = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(after_text)
        chunk = after_text[start:end].strip()
        chunk_lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        text = norm_space(" ".join(chunk_lines))
        choices.append({"id": letter, "text": text})

    needs_review = (len(choices) != 6)

    return {
        "qid": f"p{passage_no:02d}_q10",
        "number": 10,
        "type": "summary",
        "prompt": prompt,
        "intro": intro,
        "max_selections": 3,
        "choices": choices,
        "needs_review": needs_review,
        "choices_count": len(choices),
    }

def main() -> None:
    print(f"[INFO] PDF_PATH: {PDF_PATH.resolve()}")
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

    full_text = read_pdf_text(PDF_PATH)
    passages = split_passages(full_text)
    print(f"[INFO] Matched passages: {len(passages)}")

    out: List[Dict] = []
    failed = 0
    failed_ids: List[int] = []

    for pno, title, block in passages:
        q10_block = extract_q10_block(block)
        if not q10_block:
            failed += 1
            failed_ids.append(pno)
            continue

        q10 = parse_q10(q10_block, pno, debug=(pno == 1))
        if not q10:
            failed += 1
            failed_ids.append(pno)

            # Print a compact preview for failed ones
            print(f"\n[DEBUG] ===== FAILED Passage {pno}: {title} =====")
            q10_clean = clean_text(q10_block)

            parts = ANSWER_CHOICES_SPLIT_RE.split(q10_clean, maxsplit=1)
            if len(parts) == 2:
                after_text = parts[1]
                print("[DEBUG] After 'Answer Choices' preview (first 30 lines):")
                for ln in after_text.splitlines()[:30]:
                    print(repr(ln))
                # Also show how many option markers we detect
                ms = list(OPT_START_RE.finditer(after_text))
                print(f"[DEBUG] option markers found in failed passage: {len(ms)}")
                if ms:
                    print("[DEBUG] first 8 marker lines:")
                    for m in ms[:8]:
                        start = m.start()
                        line_start = after_text.rfind("\n", 0, start) + 1
                        line_end = after_text.find("\n", start)
                        if line_end == -1:
                            line_end = len(after_text)
                        print(repr(after_text[line_start:line_end]))
            else:
                print("[DEBUG] Could not split by Answer Choices.")

            print("[DEBUG] ===========================================\n")
            continue

        out.append({"passage_no": pno, "title": title, "q10": q10})

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[INFO] Failed passages: {failed_ids}")
    print(f"[INFO] Blocks failed parse_q10: {failed}")
    print(f"[OK] Wrote {len(out)} Q10 items -> {OUT_PATH}")



if __name__ == "__main__":
    main()
