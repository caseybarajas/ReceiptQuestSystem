# Receipt Quest System

Turn your thermal receipt printer into an ADHD-friendly quest board.

Generate very granular, activation-friendly task lists that print instantly to grab your attention and get you moving.

## Setup

1. **Install Python 3.9+**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Connect your thermal printer** (USB ESC/POS compatible) and power it on
4. **Optional: Set up local AI** for better step generation:
   ```bash
   # Install Ollama (see https://ollama.ai)
   ollama pull phi3:mini
   ollama serve
   ```

## Usage

Just run it and enter your task:

```bash
python main.py
```

**What it does:**
- Prompts for a single task (e.g., "do math homework", "clean desk")
- Uses AI to break it into 10+ tiny, specific steps
- Prints a receipt with checkboxes and a motivational quote
- Makes a beep to grab your attention
- No time estimates (to avoid anxiety)

### Advanced Options

**Structured input:**
```bash
python main.py --line "Clean kitchen | wipe counters, load dishwasher, take out trash"
```

**One-shot printing:**
```bash
python main.py --task "study for exam" --once
```

**Environment defaults:**
```bash
RQS_STYLE=numbered python main.py
```

### Customizing AI Instructions

Create `ai_instructions.md` in the project root to customize how the AI generates steps:

```markdown
Always return exactly 11 objectives.
Use short, imperative sentences under 60 characters.
Include 1-2 micro-activation steps (e.g., clear space, sip water).
Do not invent specifics; keep steps generic and process-focused.
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

**Printer Issues:**
- On Windows: Select from system printers or install libusb drivers (Zadig)
- On Linux/Mac: Ensure USB printer permissions via udev rules
- Verify printer is ESC/POS compatible (most thermal receipt printers work)

**AI Generation Issues:**
- Ensure Ollama is running: `ollama serve`
- Try a different model: `ollama pull qwen2:0.5b`
- Fallback templates work without AI if needed
