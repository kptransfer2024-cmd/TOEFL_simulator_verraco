import json
import os
from pathlib import Path
from backend.importers.pdf_bank_importer import PDFBankParser

def run_importer(pdf_file: str, json_output: str, keys_file: str = None):
    """
    Main entry point to convert PDF to JSON with optional answer key merging.
    """
    if not os.path.exists(pdf_file):
        print(f"[Error] PDF not found: {pdf_file}")
        return

    # 1. Extract raw text using PyMuPDF (fitz)
    print(f"[*] Extracting text from {pdf_file}...")
    import fitz
    doc = fitz.open(pdf_file)
    raw_text = ""
    for page in doc:
        raw_text += page.get_text()
    doc.close()

    # 2. Parse text to structured data
    print("[*] Parsing structure...")
    parser = PDFBankParser()
    passages = parser.parse(raw_text)

    # 3. Optional: Merge answers from answer_keys.json
    if keys_file and os.path.exists(keys_file):
        print(f"[*] Merging keys from {keys_file}...")
        with open(keys_file, 'r', encoding='utf-8') as f:
            all_keys = json.load(f)
        
        for p in passages:
            p_id = p["id"]
            if p_id in all_keys:
                p_ans_list = all_keys[p_id]
                for idx, q in enumerate(p["questions"]):
                    if idx < len(p_ans_list):
                        # Store as list for consistency with multi-choice support
                        q["correct"] = [p_ans_list[idx].strip().upper()]

    # 4. Save to target file
    output_data = {"passages": passages}
    with open(json_output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 5. Summary report
    q_count = sum(len(p["questions"]) for p in passages)
    print("-" * 30)
    print(f"Import Task Completed:")
    print(f"- Passages: {len(passages)}")
    print(f"- Questions: {q_count}")
    print(f"- Output: {json_output}")
    print("-" * 30)

if __name__ == "__main__":
    # Configure paths
    BASE_DIR = Path(__file__).resolve().parent.parent
    run_importer(
        pdf_file=str(BASE_DIR / "data" / "reading50.pdf"),
        json_output=str(BASE_DIR / "data" / "passages.json"),
        keys_file=str(BASE_DIR / "data" / "answer_keys.json")
    )