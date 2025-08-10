# Receipt Quest System

Print ADHD-friendly, granular checklists on a thermal receipt printer so starting is easy and momentum is inevitable.

### Highlights
- Single prompt → AI generates tiny, actionable steps (first step is always a micro-activation)
- No time estimates (anxiety-safe)
- Loud, attention-grabbing print (optional beep)
- Customizable AI behavior via `ai_instructions.md`

## Quick Start

1) Install Python 3.9+

2) Install dependencies
```bash
pip install -r requirements.txt
```

3) Connect your USB ESC/POS thermal printer and power it on

4) Optional: Set up local AI (Ollama)
```bash
# Install Ollama (see https://ollama.ai)
ollama pull phi3:mini
ollama serve
```

5) Run it
```bash
python main.py
```

## What You’ll See
- Enter a task (e.g., "do math homework", "clean desk", "take a shower")
- The app prints a granular checklist with checkboxes and a short supportive quote
- Steps avoid guessing specifics (no random subjects, books, etc.)
- The first step is a tiny micro-activation to help you start

## Advanced Usage

- Structured input (title + steps):
```bash
python main.py --line "Clean kitchen | wipe counters, load dishwasher, take out trash"
```

- One-shot print:
```bash
python main.py --task "study for exam" --once
```

- Environment defaults:
```bash
RQS_STYLE=numbered python main.py
```

## Customize AI Behavior
Create `ai_instructions.md` (or point `RQS_AI_INSTRUCTIONS_PATH` to a file). Examples to include:

```markdown
Use as many short steps as necessary (8–14 typical).
Make step 1 a micro-activation (clear space, put phone away, open the task).
No times or durations. No invented specifics (subjects, books, brands).
Short, imperative sentences under 50 characters.
```

## Project Structure
```
ReceiptQuestSystem/
├── receiptquest/           # Main package
│   ├── core/              # Models and AI generation
│   ├── printing/          # Printer utils and formatting
│   └── app/               # Main application logic
├── ai_instructions.md     # AI prompt customization
├── main.py               # Entry point
└── requirements.txt      # Dependencies
```

## Troubleshooting
- On Windows, you may be prompted to select a system printer (spooler). If unavailable, it falls back to USB discovery.
- On Linux/Mac, ensure USB permissions (udev rules) and ESC/POS compatibility.
- If AI is inconsistent, edit `ai_instructions.md` to be stricter (the app appends it to every prompt).
