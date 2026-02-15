# backend/scripts/import_ql2_q9_to_json.py
from __future__ import annotations

import sys
from pathlib import Path

# Ensure "backend/" is on sys.path so we can import importers/*
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import json

from importers.q9_pdf_importer import parse_q9_pdf

ROOT = BACKEND_DIR
DATA = ROOT / "data"

def main() -> None:
    pdf_path = DATA / "ql2.pdf"
    out_path = DATA / "passages_q9.json"
    report_path = DATA / "import_report_q9.json"

    result = parse_q9_pdf(pdf_path)
    passages = result["passages"]
    warnings = result["warnings"]

    out_payload = {
        "version": 1,
        "source_pdf": str(pdf_path.name),
        "passages": passages,
    }

    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps({"warnings": warnings, "count": len(passages)}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Wrote: {out_path}")
    print(f"[OK] Wrote: {report_path}")
    if warnings:
        print("[WARN] Some issues found:")
        for w in warnings[:20]:
            print("  -", w)

if __name__ == "__main__":
    main()
