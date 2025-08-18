from typing import List, Dict
import os
import sys
import time
import argparse
import threading
import signal
from pathlib import Path

from ..printing import select_printer_target, select_printer_target_noninteractive, open_printer_from_target, print_markdown_document
from ..core.models import Quest, Objective
from ..printing.quest_formatter import print_supportive_quest
from .web_server import create_app

try:
    from ..core.quest_generator import LocalLLMQuestGenerator
except Exception:
    LocalLLMQuestGenerator = None  # type: ignore


def _prompt_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _parse_objectives(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(',') if item.strip()]


def _fallback_template_from_intent(intent: str) -> Dict[str, object]:
    text = intent.strip()
    if len(text) > 80:
        title_snippet = text[:77] + "..."
    else:
        title_snippet = text
    # naive objective split on 'and' / commas
    parts = []
    for sep in [",", " and "]:
        if sep in text.lower():
            parts = [p.strip() for p in text.replace(" and ", ",").split(",") if p.strip()]
            break
    if not parts:
        parts = [text]
    objectives = []
    for p in parts[:5]:
        objectives.append(p.capitalize())
    if len(objectives) < 2:
        objectives = [
            "Plan the task",
            objectives[0],
            "Wrap up and confirm completion",
        ]
    return {
        "title": f"Quest: {title_snippet}",
        "description": text,
        "objectives": objectives,
        "rewards": "+10 Momentum, +10 Satisfaction",
    }


def _expand_to_super_adhd(objectives: List[str], title: str, description: str) -> List[str]:
    """Return a very granular, deterministic checklist tailored for ADHD activation.

    - Avoids fabricating specific content (books, topics, etc.)
    - Uses only generic process steps; lightly adapts wording based on detected keywords
    - Expands only when the existing objective list is short (<= 3)
    """
    context = f"{title} \n {description} \n {'; '.join(objectives)}".lower()
    is_homework = any(k in context for k in ["homework", "hw", "assignment", "classwork"])
    is_math = any(k in context for k in ["math", "algebra", "geometry", "calculus", "statistics"])
    is_study = any(k in context for k in ["study", "revise", "review"]) or is_homework
    is_writing_task = any(k in context for k in ["write", "writing", "essay", "paper", "notes", "journal"]) or is_study
    is_hygiene_shower = any(k in context for k in ["shower", "bathe", "bath", "wash hair"]) 
    is_cleaning = any(k in context for k in [
        "clean", "tidy", "declutter", "organize", "vacuum", "wipe", "dishes", "kitchen", "desk", "room", "trash"
    ])
    is_email_admin = any(k in context for k in [
        "email", "inbox", "admin", "paperwork", "forms", "bills", "tax", "bank"
    ])
    is_workout = any(k in context for k in [
        "workout", "exercise", "gym", "walk", "run", "stretch", "pushup", "yoga"
    ])
    is_cooking = any(k in context for k in [
        "cook", "cooking", "meal", "breakfast", "lunch", "dinner", "prep", "food"
    ])
    is_laundry = any(k in context for k in [
        "laundry", "clothes", "wash", "dryer", "fold", "hamper"
    ])
    is_errand = any(k in context for k in [
        "grocery", "shopping", "store", "errand", "pharmacy"
    ])
    is_mindfulness = any(k in context for k in [
        "meditate", "breath", "breathing", "mindful", "mindfulness"
    ])

    # Hygiene/Shower template
    if is_hygiene_shower:
        shower_steps: List[str] = [
            "Grab towel and clean clothes",
            "Put phone away and head to bathroom",
            "Turn on water, set comfy temperature",
            "Step in and rinse",
            "Soap body",
            "Shampoo hair (if needed)",
            "Rinse off",
            "Turn water off",
            "Towel dry",
            "Get dressed",
            "Mark this as done",
        ]
        return shower_steps

    # Study/Homework/Writing template
    materials_step = None
    if is_math:
        materials_step = "Gather materials (notebook, paper, calculator)"
    elif is_writing_task or is_study:
        materials_step = "Gather materials (notebook, paper)"

    open_task_step = (
        "Take the homework out and open to the right page" if is_homework else "Open the task and load the next part"
    )
    first_unit_step = (
        "Do the first problem" if (is_math or is_homework) else "Do the first small part"
    )
    next_chunk_step = (
        "Do the next 2–3 problems" if (is_math or is_homework) else "Do the next small chunk"
    )

    granular: List[str] = []
    if is_writing_task or is_study or is_math or is_homework:
        granular.append("Grab a writing utensil")
        if materials_step:
            granular.append(materials_step)
        granular.extend([
            "Clear a small space and sit down",
            open_task_step,
            "Skim the instructions (30 seconds)",
            first_unit_step,
            "Take a quick sip of water",
            next_chunk_step,
            "Quick check and save your work",
            "Put materials back in your bag/place",
            "Mark this as done",
        ])
        return granular[:12]

    # Generic task template (no writing utensil)
    if is_cleaning:
        return [
            "Bag up obvious trash",
            "Gather tools (bin, cloth, spray)",
            "Clear a small surface",
            "Sort: keep / relocate / trash",
            "Wipe the surface",
            "Return keep items neatly",
            "Quick sweep or vacuum",
            "Take trash out",
            "Take a sip of water",
            "Mark this as done",
        ]

    if is_email_admin:
        return [
            "Open inbox/admin tab",
            "Set a 10-minute focus timer",
            "Archive obvious noise",
            "Handle one priority item",
            "Handle one small item",
            "If stuck: write a 1-sentence plan",
            "Schedule remaining for later",
            "Close the tab",
            "Mark this as done",
        ]

    if is_workout:
        return [
            "Change into comfy clothes",
            "Fill a water bottle",
            "Warm up for 1 minute",
            "Do first easy set",
            "Rest and sip water",
            "Do second set",
            "Stretch briefly",
            "Log that you moved today",
            "Mark this as done",
        ]

    if is_cooking:
        return [
            "Wash hands",
            "Gather ingredients and tools",
            "Clear a small prep space",
            "Preheat or boil if needed",
            "Do the first prep step",
            "Cook the main part",
            "Plate the food",
            "Quick wipe of the counter",
            "Enjoy a bite and mark done",
        ]

    if is_laundry:
        return [
            "Collect clothes into hamper",
            "Load washer (sort if needed)",
            "Add detergent and start",
            "Move to dryer",
            "Fold 5–10 items",
            "Put folded items away",
            "Mark this as done",
        ]

    if is_errand:
        return [
            "Write a tiny list (3 items)",
            "Grab wallet/keys/bags",
            "Head out the door",
            "Get the top 1–2 items first",
            "Get the remaining items",
            "Return home and unpack",
            "Put bags away",
            "Mark this as done",
        ]

    if is_mindfulness:
        return [
            "Sit comfortably",
            "Set a 3-minute timer",
            "Close eyes and breathe",
            "If distracted: label and return",
            "Open eyes and stretch",
            "Mark this as done",
        ]

    generic_steps: List[str] = [
        "Gather what you need",
        "Clear a small space and sit/stand to start",
        "Open the task or next part",
        "Skim goals (30 seconds)",
        "Do the first small part",
        "Take a quick sip of water",
        "Do the next small chunk",
        "Quick check and save/put aside",
        "Put things away",
        "Mark this as done",
    ]
    return generic_steps


# Removed unused interactive helper _maybe_generate_with_local_llm


def _generate_data_from_intent(intent: str, use_llm: bool) -> Dict[str, object]:
    """Generate quest data from a free-text intent using local LLM if available,
    otherwise build a simple fallback template.

    This avoids additional interactive prompts to reduce cognitive load.
    """
    text = intent.strip()
    if not text:
        return {}
    if not use_llm or LocalLLMQuestGenerator is None:
        return _fallback_template_from_intent(text)
    try:
        # Normalize compound separators
        raw = text
        separators = [" then ", " and then ", " after that ", " afterwards ", ";"]
        for sep in separators:
            # Case-insensitive replacement
            import re
            raw = re.sub(re.escape(sep), "|", raw, flags=re.IGNORECASE)
        parts = [p.strip(" ,.") for p in raw.split("|") if p.strip()] if "|" in raw else [text]

        generator = LocalLLMQuestGenerator()

        objectives: List[str] = []
        titles: List[str] = []
        text_lower = text.lower()
        wants_break = any(k in text_lower for k in [" break", "take a break", "quick break"]) or "break" in text_lower

        for idx, part in enumerate(parts):
            subj = None
            part_l = part.lower()
            cat_override = None
            if any(w in part_l for w in ["study", "homework", "assignment", "classwork", "math", "english", "essay", "paper", "writing"]):
                cat_override = "study"
                if any(w in part_l for w in ["math", "algebra", "geometry", "calculus", "statistics"]):
                    subj = "math"
                elif any(w in part_l for w in ["english", "essay", "paper", "writing"]):
                    subj = "english"

                data_g = generator.generate_granular(part, [], fast=True, category_override=cat_override, subject=subj)
            else:
                data_g = generator.generate_granular(part, [], fast=True)

            part_objs = [str(o) for o in (data_g.get("objectives", []) or [])][:9]
            if not part_objs:
                data_c = generator.generate(part, fast=True)
                part_objs = [str(o) for o in (data_c.get("objectives", []) or [])][:7]
            if idx > 0 and wants_break:
                objectives.append("Stand up and stretch briefly")
            objectives.extend(part_objs)
            t = str(data_g.get("title") or part).strip()
            if t:
                titles.append(t)

        final_title = (" → ").join(titles[:3]) if len(titles) > 1 else f"Quest: {text[:77] + '...' if len(text) > 80 else text}"
        data = {
            "title": final_title,
            "description": text,
            "objectives": objectives[:18] if objectives else _fallback_template_from_intent(text)["objectives"],
            "rewards": "+10 Momentum, +10 Satisfaction",
        }
        return data
    except Exception:
        return _fallback_template_from_intent(text)


def _auto_markdown_from_text(text: str) -> str:
    """Convert free text into a pleasant Markdown layout automatically.

    Heuristics:
    - If text already looks like Markdown, return as-is.
    - If multi-line, first line is title (H1), remaining lines become bullets.
    - If single line with multiple sentences or comma/semicolon/"and" items, use title + bullets.
    - Otherwise, just emit an H1 from the text.
    """
    t = (text or "").strip()
    if not t:
        return ""
    # Looks like Markdown already
    stripped = t.lstrip()
    if stripped.startswith(("# ", "## ", "### ", "- ", "* ", "> ", "```", "1. ")) or "\n- " in t or "\n* " in t:
        return t

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if len(lines) >= 2:
        title = lines[0]
        items = lines[1:]
        bullets = "\n".join(f"- {it}" for it in items[:20])
        return f"# {title}\n\n{bullets}"

    # Single-line heuristics
    import re
    # Identify first sentence as title
    sentence_parts = re.split(r"[.!?]+\s+", t)
    sentence_parts = [p.strip(" ,;:-") for p in sentence_parts if p.strip()]
    title = sentence_parts[0] if sentence_parts else t
    remainder = t[len(title):].strip()

    # Try to extract list-like items from remainder
    list_candidates = re.split(r"\s*(?:,|;|\band\b)\s*", remainder, flags=re.IGNORECASE)
    list_candidates = [c.strip() for c in list_candidates if c.strip()]
    items: List[str] = []
    if len(list_candidates) >= 2:
        items = list_candidates
    elif len(sentence_parts) >= 2:
        items = sentence_parts[1:]

    if items and len(items) >= 2:
        bullets = "\n".join(f"- {it}" for it in items[:10])
        return f"# {title}\n\n{bullets}"
    return f"# {title}"


def run():
    """Main entry point for the Receipt Quest System."""
    # CLI args and environment-driven defaults
    parser = argparse.ArgumentParser(description="Receipt Quest System")
    parser.add_argument(
        "--mode",
        choices=["markdown", "quest"],
        default=os.getenv("RQS_MODE", "markdown"),
        help=argparse.SUPPRESS,
    )
    # Simplified: make Express · Super ADHD the implicit default; keep style for flexibility
    parser.add_argument(
        "--style",
        choices=["numbered", "checkbox"],
        default=os.getenv("RQS_STYLE", "checkbox"),
        help=argparse.SUPPRESS,
    )
    # Always ON: local LLM generation
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=True,
        help=argparse.SUPPRESS,
    )
    # ADHD granular expansion not default; allow override via env
    parser.add_argument(
        "--adhd-mode",
        choices=["regular", "super"],
        default=(os.getenv("RQS_ADHD_MODE", "regular").lower()),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--line",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--task",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--title",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--steps",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--description",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run as a small password-protected web server instead of CLI.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("RQS_HOST", "127.0.0.1"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("RQS_PORT", "54873")),
        help=argparse.SUPPRESS,
    )
    args, _ = parser.parse_known_args()

    # Respect parsed/default mode and ADHD setting
    args.mode = (args.mode or "markdown").lower()
    args.adhd_mode = (args.adhd_mode or "regular").lower()

    if args.web:
        # Non-interactive printer target detection for server mode
        try:
            target = select_printer_target_noninteractive()
            app = create_app(
                printer_target=target,
                default_step_style=args.style,
                use_llm=args.use_llm,
                adhd_mode=args.adhd_mode,
            )
            # Prefer waitress; a unified file-watcher (below) handles reloads when enabled
            try:
                from waitress import serve  # type: ignore
                print(f"Starting server on {args.host}:{args.port}")
                serve(app, host=args.host, port=args.port)
            except ImportError:
                print(
                    "WARNING: Waitress not installed. "
                    "Using Flask development server (not suitable for production)"
                )
                print("Install waitress with: pip install waitress")
                print(f"Starting development server on {args.host}:{args.port}")
                app.run(host=args.host, port=args.port)
            except Exception as e:
                print(f"Failed to start server: {e}")
                return
        except Exception as e:
            print(f"Failed to create app: {e}")
            return
        return

    # Always prefer LLM generation; if unavailable, fallback will be used silently

    target = select_printer_target()

    # Unified autoreload: enabled when RQS_RELOAD=1 or when running from a git checkout with a TTY
    def _env_truthy(name: str, default: bool = False) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in {"1", "true", "yes", "on"}

    enable_reload = _env_truthy("RQS_RELOAD", default=sys.stdin.isatty())

    # SIGHUP handler: systemd can reload by sending HUP
    def _handle_sighup(signum, frame):  # type: ignore[no-redef]
        print("Received SIGHUP. Restarting...")
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    try:
        signal.signal(signal.SIGHUP, _handle_sighup)
    except Exception:
        pass

    # Simple autoreloader (standard library only)
    if enable_reload:
        def _scan_tree(root: Path) -> Dict[str, float]:
            mtimes: Dict[str, float] = {}
            for dirpath, dirnames, filenames in os.walk(str(root)):
                # Skip noisy/irrelevant directories
                dirnames[:] = [d for d in dirnames if d not in {
                    "__pycache__", ".git", ".venv", "venv", ".mypy_cache", ".pytest_cache"
                }]
                for fname in filenames:
                    if not fname.endswith(".py"):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        mtimes[fpath] = os.stat(fpath).st_mtime
                    except Exception:
                        pass
            return mtimes

        watch_root = Path(__file__).resolve().parents[1]  # receiptquest/
        _baseline = _scan_tree(watch_root)

        def _watch_and_restart() -> None:
            nonlocal _baseline
            while True:
                time.sleep(1.0)
                current = _scan_tree(watch_root)
                changed = False
                if current.keys() != _baseline.keys():
                    changed = True
                else:
                    for p, m in current.items():
                        if _baseline.get(p) != m:
                            changed = True
                            break
                if changed:
                    print("Detected code changes. Restarting...")
                    sys.stdout.flush()
                    os.execv(sys.executable, [sys.executable] + sys.argv)

        threading.Thread(target=_watch_and_restart, daemon=True).start()

    while True:
        print("\n--- Create a New Quest ---")

        non_interactive_input = any([args.line, args.task, args.title, args.steps, args.description])

        if non_interactive_input:
            if args.line:
                line = args.line.strip()
                if "|" in line:
                    raw_title, raw_steps = line.split("|", 1)
                    title = raw_title.strip() or "Untitled Quest"
                    description = args.description.strip() if isinstance(args.description, str) else ""
                    objectives = _parse_objectives(raw_steps)
                    data = {"title": title, "description": description, "objectives": objectives}
                else:
                    data = _generate_data_from_intent(line, args.use_llm)
                    title = str(data.get("title", "Untitled Quest")) or "Untitled Quest"
                    description = str(data.get("description", ""))
                    objectives = list(data.get("objectives", []))  # type: ignore[assignment]
            elif args.title or args.steps or args.description:
                title = (args.title or "Untitled Quest").strip() or "Untitled Quest"
                description = (args.description or "").strip()
                objectives = _parse_objectives(args.steps or "")
                if not objectives and args.task:
                    # fall back to intent generation for steps if steps not provided
                    data = _generate_data_from_intent(args.task, args.use_llm)
                    objectives = list(data.get("objectives", []))  # type: ignore[assignment]
                data = {"title": title, "description": description, "objectives": objectives}
            elif args.task:
                data = _generate_data_from_intent(args.task, args.use_llm)
                title = str(data.get("title", "Untitled Quest")) or "Untitled Quest"
                description = str(data.get("description", ""))
                objectives = list(data.get("objectives", []))  # type: ignore[assignment]

            next_action = None
            total_estimate_mins = None
            step_style = args.style
            cue_text = None
            timer_minutes = None

            # Super ADHD expansion (non-interactive)
            if args.adhd_mode == "super":
                if LocalLLMQuestGenerator is not None:
                    try:
                        generator = LocalLLMQuestGenerator()
                        data_g = generator.generate_granular(title or description or "", objectives, fast=True)
                        gen_objs = list(data_g.get("objectives", []) or [])  # type: ignore[assignment]
                        if gen_objs:
                            objectives = [str(o) for o in gen_objs]
                            title = str(data_g.get("title", title) or title)
                            description = str(data_g.get("description", description) or description)
                        else:
                            # Fallback to coarse generation if granular empty
                            data = generator.generate(title or description or "", fast=True)
                            if data.get("objectives"):
                                objectives = list(data.get("objectives", []))  # type: ignore[assignment]
                                title = str(data.get("title", title) or title)
                                description = str(data.get("description", description) or description)
                    except Exception:
                        objectives = _expand_to_super_adhd(objectives, title, description)
                elif len(objectives) <= 3:
                    objectives = _expand_to_super_adhd(objectives, title, description)

        elif args.mode == "quest":
            # Single, flexible prompt. Supports: "Title | step1, step2, step3" or free-text intent
            line = _prompt_input(
                "Task (or 'Title | step1, step2, ...'). Leave blank to quit: "
            ).strip()
            if not line:
                print("Farewell, adventurer!")
                break

            if "|" in line:
                # Inline structured entry
                raw_title, raw_steps = line.split("|", 1)
                title = raw_title.strip() or "Untitled Quest"
                description = ""
                objectives = _parse_objectives(raw_steps)
                data = {"title": title, "description": description, "objectives": objectives}
            else:
                # Free text intent -> generate or fallback template
                data = _generate_data_from_intent(line, args.use_llm)
                title = str(data.get("title", "Untitled Quest")) or "Untitled Quest"
                description = str(data.get("description", ""))
                objectives = list(data.get("objectives", []))  # type: ignore[assignment]

            # Defaults to reduce prompts
            next_action = None
            total_estimate_mins = None
            step_style = args.style
            cue_text = None
            timer_minutes = None

            # Super ADHD expansion (interactive quest)
            if args.adhd_mode == "super":
                # Prefer LLM granular generation; fallback to deterministic expansion
                if LocalLLMQuestGenerator is not None:
                    try:
                        generator = LocalLLMQuestGenerator()
                        data_g = generator.generate_granular(title or description or "", objectives, fast=True)
                        # Prefer generated objectives if they exist
                        gen_objs = list(data_g.get("objectives", []) or [])  # type: ignore[assignment]
                        if gen_objs:
                            objectives = [str(o) for o in gen_objs]
                            # Fill missing title/description if provided
                            title = str(data_g.get("title", title) or title)
                            description = str(data_g.get("description", description) or description)
                        else:
                            data = generator.generate(title or description or "", fast=True)
                            if data.get("objectives"):
                                objectives = list(data.get("objectives", []))  # type: ignore[assignment]
                                title = str(data.get("title", title) or title)
                                description = str(data.get("description", description) or description)
                    except Exception:
                        objectives = _expand_to_super_adhd(objectives, title, description)
                elif len(objectives) <= 3:
                    objectives = _expand_to_super_adhd(objectives, title, description)
        else:
            # Markdown echo mode: print exactly what the user types, rendered as Markdown
            text = _prompt_input(
                "Enter text to print (Markdown supported). Leave blank to quit: "
            ).strip("\n")
            if not text:
                print("Farewell, adventurer!")
                break
            # Prepare variables expected by the common print block
            title = ""
            description = ""
            objectives = []
            next_action = None
            total_estimate_mins = None
            step_style = args.style
            cue_text = None
            timer_minutes = None
            data = {}
        # fallthrough: handled above for quest/markdown modes

        # Print either a quest or raw Markdown, depending on mode
        print("\nPrinting...")
        printer = open_printer_from_target(target)
        try:
            if args.mode == "markdown" and not non_interactive_input:
                # Auto-convert plain text to pleasant Markdown
                text_md = _auto_markdown_from_text(text)
                print_markdown_document(printer, text_md)
            else:
                # Prefer supportive layout for quests
                quest = Quest.new(
                    title=title,
                    description=description,
                    objectives=[Objective(text=o) for o in objectives],
                    next_action=next_action,
                    total_estimate_mins=total_estimate_mins,
                )
                print_supportive_quest(
                    printer,
                    quest,
                    step_style=step_style,
                    include_activation=True,
                    cue_text=cue_text,
                    timer_minutes=timer_minutes,
                    qr_link=None,
                    show_time_estimates=False,
                )
        finally:
            try:
                close_fn = getattr(printer, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass

        if non_interactive_input or args.once:
            print("Farewell, adventurer!")
            break
        elif args.mode in {"quest", "markdown"}:
            again = _prompt_input("\nPress Enter to print another, or 'q' to quit: ").strip().lower()
            if again in {"q", "quit"}:
                print("Farewell, adventurer!")
                break
        else:
            print("Farewell, adventurer!")
            break


if __name__ == "__main__":
    run()
