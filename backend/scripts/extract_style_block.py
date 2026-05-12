"""One-shot helper for Phase 5: remove the inline <style> block from
checkin-planner.html and replace it with a <link> to the extracted CSS file.

Idempotent: runs as a no-op if the inline block is already gone.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    html_path = repo_root / "checkin-planner.html"

    text = html_path.read_text(encoding="utf-8")
    start = text.find("<style>\n  :root {")
    if start == -1:
        print("Inline style block already removed - nothing to do.")
        return 0
    end = text.find("</style>", start)
    if end == -1:
        print("ERROR: opening <style> found but no closing </style>")
        return 1
    end += len("</style>")
    block = text[start:end]
    print(f"Inline style block: {end - start} chars, {block.count(chr(10))} lines")

    replacement = "<link rel=\"stylesheet\" href=\"{% static 'planner/styles/main.css' %}\">"
    new_text = text[:start] + replacement + text[end:]

    with open(html_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_text)
    print(f"Done. New file size: {len(new_text)} chars (was {len(text)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
