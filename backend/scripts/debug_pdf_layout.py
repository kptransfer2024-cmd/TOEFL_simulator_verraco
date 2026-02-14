from __future__ import annotations

import sys
from pathlib import Path


def _find_backend_dir() -> Path:
    here = Path(__file__).resolve()
    backend_dir = here.parents[1]
    return backend_dir


def main() -> None:
    backend_dir = _find_backend_dir()
    sys.path.insert(0, str(backend_dir))

    from importers.pdf_bank_importer import _extract_pdf_lines  # type: ignore
    from importers.text_cleaner import clean_lines  # type: ignore
    from importers.key_parser import parse_keys_from_lines  # type: ignore

    pdf_candidates = [
        backend_dir / "reading50.pdf",
        backend_dir.parent / "reading50.pdf",
    ]
    pdf_path = next((p for p in pdf_candidates if p.exists()), None)
    if pdf_path is None:
        raise FileNotFoundError("reading50.pdf not found in backend/ or project root")

    raw_lines, page_count, engine, extract_warnings = _extract_pdf_lines(pdf_path)
    lines = clean_lines(raw_lines)

    print("PDF debug")
    print(f"- PDF: {pdf_path}")
    print(f"- Engine: {engine}")
    print(f"- Pages: {page_count}")
    print(f"- Raw lines: {len(raw_lines)}")
    print(f"- Clean lines: {len(lines)}")
    if extract_warnings:
        print(f"- Extract warnings: {len(extract_warnings)}")
        for w in extract_warnings[:10]:
            print(f"  - {w}")

    # Show first 80 lines to understand formatting
    print("\n--- First 80 cleaned lines ---")
    for i, ln in enumerate(lines[:80], start=1):
        print(f"{i:03d}: {ln}")

    # Search for likely markers
    markers = ["Passage", "Questions", "Answer", "Keys", "Key", "1.", "2.", "A.", "B.", "C.", "D."]
    print("\n--- Marker hits (first 50) ---")
    hits = 0
    for i, ln in enumerate(lines, start=1):
        if any(m in ln for m in markers):
            print(f"{i:05d}: {ln}")
            hits += 1
            if hits >= 50:
                break

    # Parse keys and report shape
    keys_res = parse_keys_from_lines(lines)
    print("\nKeys parse result")
    print(f"- Passages with keys: {len(keys_res.keys)}")
    print(f"- Key warnings: {len(keys_res.warnings)}")
    for w in keys_res.warnings[:20]:
        print(f"  - {w}")

    if keys_res.keys:
        sample_pid = sorted(keys_res.keys.keys())[0]
        sample_keys = keys_res.keys[sample_pid]
        print(f"\nSample keys for passage {sample_pid}:")
        print(" ".join(sample_keys[:40]))


if __name__ == "__main__":
    main()
