from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable
import textwrap

from receiptquest.printing import (
    select_printer_target,
    select_printer_target_noninteractive,
    open_printer_from_target,
    get_printer_columns,
    try_beep,
)


def _wrap(text: str, width: int) -> Iterable[str]:
    wrapper = textwrap.TextWrapper(
        width=width, break_long_words=False, break_on_hyphens=False
    )
    return wrapper.wrap(text)


def print_markdown_document(printer, markdown_text: str) -> None:
    """Best-effort Markdown-to-receipt printing.

    Handles:
    - # / ## headings (bold, larger for H1)
    - bullet and numbered lists
    - fenced code blocks (monospace-style block)
    - blockquotes
    - basic paragraph wrapping
    """
    cols = get_printer_columns(printer, default=42)

    in_code_block = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip("\n")

        # Fenced code block toggle
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                printer.text("\n")
            else:
                printer.text("\n")
            continue

        if in_code_block:
            # Print code as-is with small indent; avoid wrapping
            printer.set(align="left")
            printer.text("  " + line + "\n")
            continue

        stripped = line.lstrip()
        if not stripped:
            printer.text("\n")
            continue

        # Headings
        if stripped.startswith("# "):
            title = stripped[2:].strip() or "Untitled"
            printer.set(align="left", bold=True, width=2, height=2)
            printer.text(title[:cols] + "\n")
            printer.set(align="left", bold=False, width=1, height=1)
            printer.text("\n")
            continue
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            printer.set(align="left", bold=True)
            for w in _wrap(title, cols):
                printer.text(w + "\n")
            printer.set(align="left", bold=False)
            continue

        # Blockquote
        if stripped.startswith("> "):
            content = stripped[2:].strip()
            prefix = "│ "
            wrapper = textwrap.TextWrapper(
                width=cols,
                initial_indent=prefix,
                subsequent_indent=" " * len(prefix),
                break_long_words=False,
                break_on_hyphens=False,
            )
            for w in wrapper.wrap(content):
                printer.text(w + "\n")
            continue

        # Bulleted list
        if stripped.startswith(('- ', '* ')):
            content = stripped[2:].strip()
            prefix = "• "
            wrapper = textwrap.TextWrapper(
                width=cols,
                initial_indent=prefix,
                subsequent_indent=" " * len(prefix),
                break_long_words=False,
                break_on_hyphens=False,
            )
            for w in wrapper.wrap(content):
                printer.text(w + "\n")
            continue

        # Numbered list (1. 2. ...)
        if any(stripped.startswith(f"{n}. ") for n in range(1, 10)):
            # Preserve the existing number as prefix
            number, rest = stripped.split(". ", 1)
            prefix = f"{number}. "
            wrapper = textwrap.TextWrapper(
                width=cols,
                initial_indent=prefix,
                subsequent_indent=" " * len(prefix),
                break_long_words=False,
                break_on_hyphens=False,
            )
            for w in wrapper.wrap(rest.strip()):
                printer.text(w + "\n")
            continue

        # Regular paragraph
        for w in _wrap(stripped, cols):
            printer.text(w + "\n")

    # Footer spacing and cut
    printer.text("\n")
    try_beep(printer, count=1, duration=2)
    printer.text("\n")
    try:
        printer.cut()
    except Exception:
        # Some printers may not support cut; it's fine
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print a Markdown file to the ESC/POS printer using ReceiptQuest utilities.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to a Markdown file. Defaults to tests/sample.md",
    )
    parser.add_argument(
        "--noninteractive",
        action="store_true",
        help="Select printer non-interactively (env vars or first available)",
    )
    args = parser.parse_args()

    if args.path:
        markdown_path = Path(args.path)
    else:
        markdown_path = Path(__file__).with_name("sample.md")

    if not markdown_path.exists():
        raise SystemExit(f"File not found: {markdown_path}")

    md_text = markdown_path.read_text(encoding="utf-8")

    target = (
        select_printer_target_noninteractive()
        if args.noninteractive
        else select_printer_target()
    )
    printer = open_printer_from_target(target)

    try:
        print_markdown_document(printer, md_text)
    finally:
        try:
            close_fn = getattr(printer, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass


if __name__ == "__main__":
    main()


