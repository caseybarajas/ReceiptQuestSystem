#!/usr/bin/env python3
"""Entry point for Receipt Quest System."""

# Ensure environment from .env-like files is loaded before anything else
try:
    from receiptquest.app.config import load_env_from_files  # type: ignore
    load_env_from_files(override=False)
except Exception:
    pass

from receiptquest.app.main import run

if __name__ == "__main__":
    run()