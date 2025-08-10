from typing import List, Tuple
import os
import sys
import argparse

# Ensure project root on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from printer_utils import select_printer_target, open_printer_from_target, print_text_document


def parse_quest_from_text(text: str) -> Tuple[str, str, List[str]]:
    """Parse a simple text format into (title, description, objectives).

    Supported formats:
    - Structured headers (case-insensitive):
      Title: <title>
      Description:
        <free text lines>
      Objectives:
        - do this
        - do that

    - Minimal fallback:
      First non-empty line is title; rest is description; no objectives.
    """
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    title = ""
    description_lines: List[str] = []
    objectives: List[str] = []

    section = None  # 'desc' or 'obj'
    found_any_header = False

    def is_header(s: str, name: str) -> bool:
        s_strip = s.strip().lower()
        return s_strip == f"{name.lower()}:" or s_strip.startswith(f"{name.lower()}: ")

    i = 0
    while i < len(lines):
        line = lines[i]
        if is_header(line, "Title"):
            found_any_header = True
            title = line.split(":", 1)[1].strip() if ":" in line else ""
            section = None
            i += 1
            continue
        if is_header(line, "Description"):
            found_any_header = True
            section = 'desc'
            i += 1
            continue
        if is_header(line, "Objectives"):
            found_any_header = True
            section = 'obj'
            i += 1
            continue

        if section == 'desc':
            description_lines.append(line)
        elif section == 'obj':
            s = line.strip()
            if s.startswith("- "):
                objectives.append(s[2:].strip())
            elif s.startswith("[ ] "):
                objectives.append(s[4:].strip())
            elif s:
                # Treat any non-empty line in objectives as an item
                objectives.append(s)
        i += 1

    if not found_any_header:
        # Minimal fallback: first non-empty line = title, rest description
        non_empty = [ln for ln in lines if ln.strip()]
        if non_empty:
            title = non_empty[0].strip()
            rest_started = False
            for ln in lines:
                if not rest_started:
                    if ln.strip() == title:
                        rest_started = True
                        continue
                description_lines.append(ln)

    description = "\n".join(description_lines).strip()
    title = title.strip() or "Untitled Quest"
    return title, description, objectives


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a quest from a text file using the app's formatting.")
    parser.add_argument("path", nargs="?", help="Path to the text file with quest content")
    args = parser.parse_args()

    if args.path:
        path = args.path
    else:
        path = input("Enter path to text file: ").strip()

    if not os.path.isfile(path):
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    title, description, objectives = parse_quest_from_text(content)

    target = select_printer_target()
    printer = open_printer_from_target(target)
    try:
        # Print clean text: bold title + wrapped description; ignore objectives and header
        body = description
        if objectives:
            # Optionally append objectives into body for a plain text print
            body += ("\n\n" if body else "") + "\n".join(f"- {o}" for o in objectives)
        print_text_document(
            printer_instance=printer,
            title=title,
            body=body,
        )
    finally:
        try:
            close_fn = getattr(printer, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass


if __name__ == "__main__":
    main()


