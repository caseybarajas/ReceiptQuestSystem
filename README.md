# Receipt Quest System

Turn any task into a tiny, ADHD-friendly checklist and print it to a thermal receipt printer.

## Features
- Single prompt → tiny, actionable steps (first step is a micro-activation)
- No time estimates (anxiety-safe)
- Clean, readable receipts
- Optional local AI via Ollama
- Behavior is customizable in `ai_instructions.md`

## Quick Start (CLI)
1) Python 3.10+ required

2) Install dependencies
```bash
pip install -r requirements.txt
```

3) Connect your USB ESC/POS thermal printer and power it on

4) Optional: Local AI with Ollama
```bash
ollama pull qwen2:0.5b
ollama serve
```

5) Run
```bash
python main.py
```

### What to expect
- Enter a task (e.g., "clean desk", "take a shower")
- Prints a short, granular checklist with checkboxes
- Avoids guessing specifics (no random subjects, brands, etc.)
- First step is always a small activation

## Advanced (CLI)
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

## Web Server (Login + CSRF)
Run a small password-protected web UI.

### Install on Ubuntu
```bash
bash scripts/install-ubuntu.sh
```
This will:
- Create a venv, install dependencies, add a USB printer udev rule
- Ask for an admin username/password (min 12 chars)
- Write credentials to config (user: `~/.config/receiptquest/config.json`, system: `/etc/receiptquest/config.json`)
- Write `/etc/receiptquest/env` with host/port and `RQS_CONFIG_PATH`

### Start the server
```bash
receiptquest-web
```
Defaults to `0.0.0.0:54873`. Change host/port in `/etc/receiptquest/env`.

### Credentials (priority)
1) Config file (if `RQS_CONFIG_PATH` is set; otherwise user config → system config)
2) Env files: `/etc/receiptquest/env` and project `.env`

Provide either:
- `RQS_WEB_USER` and `RQS_WEB_PASS` (simplest)
- or `RQS_WEB_USER`, `RQS_WEB_HASH`, `RQS_WEB_SALT`, `RQS_PBKDF2_ITERATIONS`

If you use `RQS_WEB_PASS`, the server derives hash/salt in memory at startup.

### Sample .env
```env
# Web server
RQS_HOST=0.0.0.0
RQS_PORT=54873

# Admin login (use either PASS or HASH/SALT)
RQS_WEB_USER=admin
RQS_WEB_PASS=change-me-please
# RQS_WEB_HASH=...
# RQS_WEB_SALT=...
# RQS_PBKDF2_ITERATIONS=200000

# Printer (non-interactive selection)
# RQS_PRINTER_KIND=usb            # or win32
# RQS_USB_VID=0x0416
# RQS_USB_PID=0x5011
# RQS_PRINTER_NAME="Your Windows Printer"

# Optional LLM
# RQS_MODEL=qwen2:0.5b
# RQS_OLLAMA_URL=http://127.0.0.1:11434
```

### Environment variables
Core
- `RQS_HOST`, `RQS_PORT`: Bind host/port
- `RQS_COOKIE_SECURE=1`: Secure cookies (HTTPS)
- `RQS_HSTS=1`: Add HSTS header (only with HTTPS)
- `RQS_CONFIG_PATH`: Explicit config path
- `RQS_ENV_PATH`: Explicit env file to load

Auth
- `RQS_WEB_USER`, `RQS_WEB_PASS` (or)
- `RQS_WEB_USER`, `RQS_WEB_HASH`, `RQS_WEB_SALT`, `RQS_PBKDF2_ITERATIONS`

Printer
- `RQS_PRINTER_KIND`: `usb` or `win32`
- `RQS_USB_VID`, `RQS_USB_PID` for `usb`
- `RQS_PRINTER_NAME` for `win32`

LLM (optional)
- `RQS_MODEL` (default `qwen2:0.5b`), `RQS_OLLAMA_URL` (default `http://127.0.0.1:11434`)

## Customize AI Behavior
Create `ai_instructions.md` (or set `RQS_AI_INSTRUCTIONS_PATH`). Example:
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
│   └── app/               # Web + CLI app
├── ai_instructions.md     # AI prompt customization
├── main.py                # Entry point
└── requirements.txt       # Dependencies
```

## Troubleshooting
- Can’t log in? Check `~/.config/receiptquest/config.json` or `/etc/receiptquest/config.json` for `RQS_WEB_USER`, `RQS_WEB_HASH`, `RQS_WEB_SALT`.
- Using `.env`? Keep it in the project root. Provide `RQS_WEB_USER` + `RQS_WEB_PASS` or hash/salt vars.
- Permission denied writing `/etc/.../config.json`? Run as root or point `RQS_CONFIG_PATH` to your user config path.
- Reset credentials: remove hash/salt from the config and start with `RQS_WEB_PASS` in env; it will be re-derived.
