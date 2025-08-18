from __future__ import annotations

from typing import Iterable, List, Tuple, Dict
import textwrap
import re

from .printer_utils import (
    get_printer_columns,
    try_beep,
)


def _wrap(text: str, width: int) -> Iterable[str]:
    wrapper = textwrap.TextWrapper(
        width=width, break_long_words=False, break_on_hyphens=False
    )
    return wrapper.wrap(text)


def _print_segments(printer, segments: List[Tuple[str, Dict[str, bool]]]) -> None:
    """Print a line composed of styled segments; resets style at end."""
    for text, style in segments:
        printer.set(
            align="left",
            bold=bool(style.get("bold")),
            underline=1 if style.get("underline") else 0,
        )
        if text:
            printer.text(text)
    # Reset style and end line
    printer.set(align="left", bold=False, underline=0)
    printer.text("\n")


def _parse_inline_md(text: str) -> List[Tuple[str, Dict[str, bool]]]:
    """Parse inline Markdown for bold (** or __), italic (* or _ => underline), and `code`.

    Returns list of (text, style) where style contains keys: bold, underline.
    Italic is mapped to underline (ESC/POS has no italics). Inline code is emitted
    as plain text surrounded by backticks (since monospace is default on receipts).
    Links [text](url) are rendered as 'text (url)'. Images ![alt](url) -> 'alt: url'.
    """
    # Handle links and images first to avoid interfering with other markers
    def replace_link(match: re.Match) -> str:
        label = match.group(1).strip()
        url = match.group(2).strip()
        return f"{label} ({url})"

    def replace_image(match: re.Match) -> str:
        alt = (match.group(1) or "").strip()
        url = match.group(2).strip()
        return f"{alt}: {url}" if alt else url

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, text)

    segments: List[Tuple[str, Dict[str, bool]]] = []
    buf: List[str] = []
    bold = False
    italic = False
    code = False

    i = 0
    while i < len(text):
        ch = text[i]
        # Escape sequence \
        if ch == "\\" and i + 1 < len(text):
            buf.append(text[i + 1])
            i += 2
            continue
        # Inline code toggle `
        if ch == "`":
            # flush current buffer with current style
            if buf:
                segments.append(("".join(buf), {"bold": bold, "underline": italic}))
                buf = []
            # Include the backtick visibly to suggest code
            code = not code
            segments.append(("`", {"bold": False, "underline": False}))
            i += 1
            continue
        if code:
            buf.append(ch)
            i += 1
            continue
        # Bold toggles ** or __
        if text.startswith("**", i) or text.startswith("__", i):
            if buf:
                segments.append(("".join(buf), {"bold": bold, "underline": italic}))
                buf = []
            bold = not bold
            i += 2
            continue
        # Italic toggles * or _
        if ch in ("*", "_"):
            if buf:
                segments.append(("".join(buf), {"bold": bold, "underline": italic}))
                buf = []
            italic = not italic
            i += 1
            continue

        buf.append(ch)
        i += 1

    if buf:
        segments.append(("".join(buf), {"bold": bold, "underline": italic}))

    # If code was left open, close with backtick visually
    if code:
        segments.append(("`", {"bold": False, "underline": False}))

    return segments


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
            parts = _parse_inline_md(title)
            _print_segments(printer, parts)
            continue
        if stripped.startswith("### "):
            title = stripped[4:].strip()
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

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            printer.text("-" * cols + "\n")
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
                _print_segments(printer, _parse_inline_md(w))
            continue

        # Numbered list (1. 2. ...)
        if re.match(r"^\d+\.\s+", stripped):
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
                _print_segments(printer, _parse_inline_md(w))
            continue

        # Simple table support (| a | b |)
        if stripped.startswith("|") and stripped.endswith("|") and "|" in stripped[1:-1]:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            col_width = max(3, (cols - (len(cells) + 1)) // max(1, len(cells)))
            line_out = "|" + "|".join(c[:col_width].ljust(col_width) for c in cells) + "|"
            printer.text(line_out + "\n")
            continue

        # Regular paragraph
        for w in _wrap(stripped, cols):
            _print_segments(printer, _parse_inline_md(w))

    # Footer spacing and cut
    printer.text("\n")
    try_beep(printer, count=1, duration=2)
    printer.text("\n")
    try:
        printer.cut()
    except Exception:
        # Some printers may not support cut; it's fine
        pass


