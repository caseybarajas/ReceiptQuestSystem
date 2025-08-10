from typing import Any
import os
import sys

# Ensure project root is on sys.path when running this script directly
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from printer_utils import select_printer_target, open_printer_from_target


def _prompt_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _safe_feed(printer_instance: Any, lines: int = 2) -> None:
    try:
        feed_fn = getattr(printer_instance, "feed", None)
        if callable(feed_fn):
            feed_fn(lines)
        else:
            printer_instance.text("\n" * lines)
    except Exception:
        printer_instance.text("\n" * lines)


if __name__ == "__main__":
    target = select_printer_target()

    while True:
        text = _prompt_input("Enter text to print (blank to quit): ")
        if text.strip() == "":
            print("Done.")
            break

        printer = open_printer_from_target(target)
        try:
            printer.text(text + "\n")
            _safe_feed(printer, 2)
            printer.cut()
        finally:
            try:
                close_fn = getattr(printer, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass


