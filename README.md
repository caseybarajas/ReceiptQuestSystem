## Receipt Quest System

Type anything. It prints something pretty — or as a checklist (quest) if you want.

### Quick Start
```bash
# Universal Linux installer (creates venv, udev rule, launchers)
bash scripts/install.sh

# Or manual
pip install -r requirements.txt
python main.py
```

Then just type. Your text is auto-formatted into a clean Markdown receipt (title + bullets when it makes sense).

### What it does
- **Default**: your input → auto Markdown → printed to your ESC/POS receipt printer.
- **Optional**: generate a tiny checklist from a task intent (quest mode).

### Minimal config (optional)
- USB printer: just plug it in. You’ll be prompted to select it the first time.
- If you know the printer ahead of time, you can set env vars to skip prompts:
```env
# For USB
RQS_PRINTER_KIND=usb
RQS_USB_VID=0x0416
RQS_USB_PID=0x5011

# For Windows printing
RQS_PRINTER_KIND=win32
RQS_PRINTER_NAME=Your Printer Name
```

### Advanced (opt-in via env)
- Switch CLI to checklist generator:
```bash
RQS_MODE=quest python main.py
```

- Make CLI quest steps extra granular:
```bash
RQS_MODE=quest RQS_ADHD_MODE=super python main.py
```

- Live reload while developing (auto-restart on changes):
```bash
RQS_RELOAD=1 python main.py
```

### Web server
```bash
python -m receiptquest.app.main --web
```
- Default host/port: `127.0.0.1:54873`
- Change via env:
```env
RQS_HOST=0.0.0.0
RQS_PORT=54873
```
- For systemd, enable reload with `RQS_RELOAD=1` and use `ExecReload=/bin/kill -HUP $MAINPID`.

Once running, the web page offers two buttons:
- **Print**: pretty-prints exactly what you typed as Markdown.
- **Print as Quest**: generates a small checklist (optionally using the local LLM if available).

### Environment variables
- Core
  - `RQS_MODE`: `markdown` (default) or `quest`
  - `RQS_ADHD_MODE`: `regular` (default) or `super`
  - `RQS_RELOAD=1`: enable autorestart on file changes
  - `RQS_HOST`, `RQS_PORT` (web only)
- Printer
  - `RQS_PRINTER_KIND` = `usb` or `win32`
  - `RQS_USB_VID`, `RQS_USB_PID` (usb)
  - `RQS_PRINTER_NAME` (win32)
- LLM (optional in quest mode)
  - `RQS_MODEL` (default `qwen2:0.5b`), `RQS_OLLAMA_URL` (default `http://127.0.0.1:11434`)

### Project layout
```
ReceiptQuestSystem/
├── receiptquest/
│   ├── app/          # CLI + web entry
│   ├── printing/     # Printing + Markdown rendering
│   └── core/         # Quest generator (optional)
├── main.py
└── requirements.txt
```

### Troubleshooting
- No printer found? Ensure it’s powered and recognized by the OS. For USB, check vendor/product IDs.
- Windows print issues? Verify `RQS_PRINTER_NAME` matches the control panel name.
- Quest generation slow/unavailable? It falls back gracefully; you can disable LLM by leaving defaults.
