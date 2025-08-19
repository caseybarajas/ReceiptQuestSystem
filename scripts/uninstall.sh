#!/usr/bin/env bash
set -euo pipefail
set -o errtrace

on_error() {
  local exit_code=$?
  echo "\n[ERROR] Uninstall failed (exit $exit_code). See messages above."
}
trap on_error ERR

log()  { printf "[INFO] %s\n" "$*"; }
ok()   { printf "[ OK ] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*"; }
err()  { printf "[FAIL] %s\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
VENV_DIR="${REPO_DIR}/.venv"

RECEIPTQUEST_SERVICE="receiptquest.service"
RECEIPTQUEST_ENV_DIR="/etc/receiptquest"
RECEIPTQUEST_UDEV_RULE="/etc/udev/rules.d/99-receiptquest-printers.rules"
BIN_CLI="/usr/local/bin/receiptquest"
BIN_WEB="/usr/local/bin/receiptquest-web"

USER_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/receiptquest"
USER_CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/receiptquest"

REMOVE_OLLAMA=0
PURGE=0
YES=0
KEEP_USER_CONFIG=0
KEEP_VENV=0

usage() {
  cat <<USAGE
Receipt Quest — Uninstaller

Removes installed system components. With --purge, also deletes user config, cache, and the local venv.

Usage: $0 [options]
  --yes                   Run non-interactively, assume Yes to prompts
  --purge                 Remove user config/cache and .venv too
  --keep-user-config      Keep ~/.config/receiptquest (overrides --purge for config)
  --keep-venv             Keep repo .venv (overrides --purge for venv)
  --remove-ollama-service Also remove the optional Ollama systemd unit/logs if created by installer
  -h|--help               Show this help
USAGE
}

while [[ ${1:-} =~ ^- ]]; do
  case "$1" in
    --yes) YES=1 ; shift ;;
    --purge) PURGE=1 ; shift ;;
    --keep-user-config) KEEP_USER_CONFIG=1 ; shift ;;
    --keep-venv) KEEP_VENV=1 ; shift ;;
    --remove-ollama-service) REMOVE_OLLAMA=1 ; shift ;;
    -h|--help) usage ; exit 0 ;;
    *) err "Unknown option: $1" ; usage ; exit 2 ;;
  esac
done

cat <<'BANNER'
============================================================
 Receipt Quest — Uninstall
============================================================
This will remove:
  - Systemd service: receiptquest.service (if present)
  - Launchers: /usr/local/bin/receiptquest{,-web}
  - System config: /etc/receiptquest/
  - Udev rule: 99-receiptquest-printers.rules

With --purge (recommended for a complete uninstall), also removes:
  - Local Python venv at .venv
  - User config at ~/.config/receiptquest
  - User cache at ~/.cache/receiptquest

Note: Group membership changes (e.g., plugdev) are not reverted automatically.
============================================================
BANNER

if [[ $YES -ne 1 ]]; then
  read -rp "Proceed with uninstall? [y/N]: " CONFIRM
  CONFIRM=$(echo "${CONFIRM:-N}" | tr '[:lower:]' '[:upper:]')
  if [[ "$CONFIRM" != "Y" ]]; then
    warn "Cancelled by user."
    exit 0
  fi
fi

log "[1/6] Stopping and removing systemd service (sudo)..."
if systemctl list-unit-files | grep -q "^${RECEIPTQUEST_SERVICE}"; then
  if systemctl is-active --quiet "$RECEIPTQUEST_SERVICE"; then
    sudo systemctl stop "$RECEIPTQUEST_SERVICE" || true
  fi
  sudo systemctl disable "$RECEIPTQUEST_SERVICE" || true
fi
if [[ -f "/etc/systemd/system/${RECEIPTQUEST_SERVICE}" ]]; then
  sudo rm -f "/etc/systemd/system/${RECEIPTQUEST_SERVICE}"
  sudo systemctl daemon-reload || true
  sudo systemctl reset-failed "$RECEIPTQUEST_SERVICE" || true
  ok "Removed systemd unit ${RECEIPTQUEST_SERVICE}."
else
  warn "Systemd unit not found: ${RECEIPTQUEST_SERVICE}"
fi

log "[2/6] Removing launchers from /usr/local/bin (sudo)..."
for bin in "$BIN_CLI" "$BIN_WEB"; do
  if [[ -f "$bin" ]]; then
    # Check symlink target first; then fall back to fixed-string grep of file contents
    if [[ -L "$bin" ]]; then
      target_path="$(readlink -f "$bin" 2>/dev/null || true)"
      if [[ -n "$target_path" && "$target_path" == *"$REPO_DIR"* ]]; then
        sudo rm -f "$bin"
        ok "Removed $bin (symlink to repo)"
        continue
      fi
    fi
    if grep -F -q "$REPO_DIR" "$bin" 2>/dev/null; then
      sudo rm -f "$bin"
      ok "Removed $bin"
    else
      warn "Skipping $bin (does not appear to belong to this install)"
    fi
  else
    warn "Not found: $bin"
  fi
done

log "[3/6] Removing system config at $RECEIPTQUEST_ENV_DIR (sudo)..."
if [[ -d "$RECEIPTQUEST_ENV_DIR" ]]; then
  sudo rm -rf "$RECEIPTQUEST_ENV_DIR"
  ok "Removed $RECEIPTQUEST_ENV_DIR"
else
  warn "Not found: $RECEIPTQUEST_ENV_DIR"
fi

log "[4/6] Removing udev rule (sudo)..."
if [[ -f "$RECEIPTQUEST_UDEV_RULE" ]]; then
  sudo rm -f "$RECEIPTQUEST_UDEV_RULE"
  sudo udevadm control --reload-rules || true
  sudo udevadm trigger || true
  ok "Removed udev rule and reloaded udev."
else
  warn "Udev rule not found: $RECEIPTQUEST_UDEV_RULE"
fi

log "[5/6] Cleaning user config/cache..."
if [[ $PURGE -eq 1 && $KEEP_USER_CONFIG -ne 1 ]]; then
  if [[ -d "$USER_CONFIG_DIR" ]]; then
    rm -rf "$USER_CONFIG_DIR"
    ok "Removed $USER_CONFIG_DIR"
  else
    warn "Not found: $USER_CONFIG_DIR"
  fi
  if [[ -d "$USER_CACHE_DIR" ]]; then
    rm -rf "$USER_CACHE_DIR"
    ok "Removed $USER_CACHE_DIR"
  else
    warn "Not found: $USER_CACHE_DIR"
  fi
else
  warn "Keeping user config/cache (use --purge to remove)."
fi

log "[6/6] Removing local Python virtual environment..."
if [[ $PURGE -eq 1 && $KEEP_VENV -ne 1 ]]; then
  if [[ -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
    ok "Removed venv at $VENV_DIR"
  else
    warn "Venv not found: $VENV_DIR"
  fi
else
  warn "Keeping venv (use --purge to remove)."
fi

if [[ $REMOVE_OLLAMA -eq 1 ]]; then
  log "Optional: Removing Ollama systemd unit and logs (sudo)..."
  if systemctl list-unit-files | grep -q "^ollama.service"; then
    sudo systemctl stop ollama.service || true
    sudo systemctl disable ollama.service || true
  fi
  if [[ -f "/etc/systemd/system/ollama.service" ]]; then
    sudo rm -f /etc/systemd/system/ollama.service
    sudo systemctl daemon-reload || true
    sudo systemctl reset-failed ollama.service || true
    ok "Removed ollama.service"
  else
    warn "Ollama unit not found; skipping"
  fi
  if [[ -d "/var/log/ollama" ]]; then
    sudo rm -rf /var/log/ollama
    ok "Removed /var/log/ollama"
  fi
fi

cat <<'DONE'
============================================================
 Uninstall complete
============================================================
If you added your user to the plugdev group during install, you may remove
yourself from that group manually if desired:
  sudo gpasswd -d "$USER" plugdev

You can delete the repository directory if you no longer need it.
DONE


