from typing import List, Optional
import textwrap
import random

from ..core.models import Quest, Objective

from .printer_utils import (
    get_printer_columns,
    _reset_text_style,
    _safe_feed,
    _separator,
    try_print_qr,
)


def _wrap_lines(text: str, width: int) -> List[str]:
    return textwrap.TextWrapper(width=width, break_long_words=False, break_on_hyphens=False).wrap(text)


def print_supportive_quest(printer, quest: Quest, step_style: str = "numbered",
                           include_activation: bool = True,
                           cue_text: Optional[str] = None,
                           timer_minutes: Optional[int] = None,
                           qr_link: Optional[str] = None,
                           show_time_estimates: bool = False) -> None:
    """ADHD-friendly print layout:
    - Big, clear title
    - Tiny set of guided steps
    - Optional "Next small action" bubble
    - Estimates if provided
    - Encouraging footer
    """

    cols = get_printer_columns(printer, default=42)

    # Optional attention beep before printing
    try:
        from .printer_utils import try_beep
        try_beep(printer, count=2, duration=3)
    except Exception:
        pass

    # Title header with top separator block
    _separator(printer)
    printer.set(align='center', bold=True, height=2, width=2)
    printer.text(quest.title.strip()[:cols] + "\n")
    _reset_text_style(printer)
    printer.set(align='center', bold=False)
    printer.text("— Focus on the first tiny step —\n")
    _reset_text_style(printer)
    printer.text("\n")

    # Description (short paragraphs)
    if quest.description.strip():
        for para in quest.description.splitlines():
            if not para.strip():
                printer.text("\n")
            else:
                for line in _wrap_lines(para.strip(), cols):
                    printer.text(line + "\n")
        printer.text("\n")

    # Activation section: concrete cue + next small action + short timer
    if include_activation and (quest.next_action or cue_text or timer_minutes):
        _separator(printer)
        printer.set(bold=True)
        printer.text("Start now:\n")
        _reset_text_style(printer)
        if cue_text:
            for line in _wrap_lines(cue_text, cols):
                printer.text(f"• {line}\n")
        if quest.next_action:
            for line in _wrap_lines(quest.next_action, cols):
                printer.text(f"→ {line}\n")
        if timer_minutes and timer_minutes > 0:
            printer.text(f"[ Set a {timer_minutes}-minute timer and just start. ]\n")
        printer.text("\n")

    # Objectives list (short & simple)
    if quest.objectives:
        _separator(printer)
        printer.set(bold=True)
        printer.text("Steps:\n")
        _reset_text_style(printer)
        for idx, obj in enumerate(quest.objectives, start=1):
            if step_style == "checkbox":
                prefix = "[ ] "
            else:
                prefix = f"{idx}. "
            wrapper = textwrap.TextWrapper(
                width=cols,
                initial_indent=prefix,
                subsequent_indent=" " * len(prefix),
                break_long_words=False,
                break_on_hyphens=False,
            )
            for line in wrapper.wrap(obj.text.strip()):
                printer.text(line + "\n")
            if show_time_estimates and obj.estimate_mins:
                printer.text(f"   (~{obj.estimate_mins} min)\n")
        printer.text("\n")

    # Estimate summary (optional)
    if show_time_estimates and quest.total_estimate_mins:
        _separator(printer)
        printer.set(bold=True)
        printer.text(f"Estimated total: ~{quest.total_estimate_mins} min\n")
        _reset_text_style(printer)
        printer.text("\n")

    # Encouraging footer
    _separator(printer)
    printer.set(align='center', bold=True)
    quotes = [
        "Start tiny. Momentum does the rest.",
        "One small step is still a step.",
        "Progress over perfection.",
        "You're already closer than before.",
        "Tiny actions. Big wins.",
        "Breathe. Start with the smallest thing.",
        "Done is better than perfect.",
        "You got this. Begin now.",
        "Tap the smallest domino.",
    ]
    printer.text(random.choice(quotes) + "\n")
    if qr_link:
        try_print_qr(printer, qr_link)
    _safe_feed(printer, 3)
    printer.cut()
