from pathlib import Path
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel


def render_markdown_to_console(markdown_text: str) -> None:
    console = Console()
    markdown = Markdown(markdown_text, code_theme="monokai")
    console.print(Panel(markdown, title="Markdown Preview", expand=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a Markdown file in the terminal using rich."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to a Markdown file. Defaults to tests/sample.md",
    )
    args = parser.parse_args()

    if args.path:
        markdown_path = Path(args.path)
    else:
        markdown_path = Path(__file__).with_name("sample.md")

    if not markdown_path.exists():
        raise SystemExit(f"File not found: {markdown_path}")

    markdown_text = markdown_path.read_text(encoding="utf-8")
    render_markdown_to_console(markdown_text)


if __name__ == "__main__":
    main()


