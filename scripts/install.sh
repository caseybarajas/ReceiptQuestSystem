#!/usr/bin/env bash
set -euo pipefail
set -o errtrace

on_error() {
  local exit_code=$?
  echo "\n[ERROR] Installer failed (exit $exit_code). See messages above."
  echo "You can re-run the installer after fixing the issue."
}
trap on_error ERR

log()  { printf "[INFO] %s\n" "$*"; }
ok()   { printf "[ OK ] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*"; }
err()  { printf "[FAIL] %s\n" "$*"; }

# Receipt Quest System — Universal Linux installer
# - Installs system deps (python3, pip, venv, libusb, udev, curl, ca-certs)
# - Creates a local venv and installs Python deps
# - Adds a permissive udev rule for USB printers (ESC/POS)
# - Creates handy launchers in /usr/local/bin
# - Optional: installs a systemd service (use interactive prompt)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
VENV_DIR="${REPO_DIR}/.venv"
PYTHON_BIN="python3"
DEFAULT_HOST="0.0.0.0"
DEFAULT_PORT="54873"

PKG=""
if command -v apt-get >/dev/null 2>&1; then
  PKG=apt
elif command -v dnf >/dev/null 2>&1; then
  PKG=dnf
elif command -v yum >/dev/null 2>&1; then
  PKG=yum
elif command -v pacman >/dev/null 2>&1; then
  PKG=pacman
elif command -v zypper >/dev/null 2>&1; then
  PKG=zypper
elif command -v apk >/dev/null 2>&1; then
  PKG=apk
else
  warn "Could not detect a supported package manager. Skipping system package installation."
fi

cat <<'BANNER'
============================================================
 Receipt Quest — Linux Installer
============================================================
This will:
  - Install system packages (python3, venv, pip, libusb, udev)
  - Create a Python venv and install dependencies
  - Configure USB printer permissions (udev rule)
  - Create launchers: receiptquest / receiptquest-web
  - Optionally install a systemd service
============================================================
BANNER

if [[ -n "$PKG" ]]; then
  log "[1/8] Installing system packages (sudo, $PKG)..."
  case "$PKG" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      sudo apt-get update -y
      sudo apt-get install -y \
        ${PYTHON_BIN} python3-venv python3-pip \
        libusb-1.0-0 \
        udev curl ca-certificates
      ;;
    dnf)
      sudo dnf -y install ${PYTHON_BIN} python3-pip \
        libusbx || true
      sudo dnf -y install libusb1 || true
      sudo dnf -y install udev curl ca-certificates || true
      ;;
    yum)
      sudo yum -y install ${PYTHON_BIN} python3-pip \
        libusbx || true
      sudo yum -y install libusb1 || true
      sudo yum -y install udev curl ca-certificates || true
      ;;
    pacman)
      sudo pacman -Sy --noconfirm ${PYTHON_BIN} python-pip libusb \
        udev curl ca-certificates
      ;;
    zypper)
      sudo zypper --non-interactive install -y ${PYTHON_BIN} python3-pip \
        libusb-1_0-0 || true
      sudo zypper --non-interactive install -y udev curl ca-certificates || true
      ;;
    apk)
      sudo apk add --no-cache python3 py3-pip libusb eudev curl ca-certificates || true
      ;;
  esac
  ok "System package step completed (some packages may already be present)."
else
  warn "Skipping system packages; please ensure python3, pip, and libusb are installed."
fi

# Ensure system temp dirs exist and are world-writable (sticky bit)
sudo mkdir -p /tmp /var/tmp
sudo chmod 1777 /tmp /var/tmp
ok "System temp directories ready."

log "[2/8] Creating Python virtual environment..."
if [[ ! -d "${VENV_DIR}" ]]; then
  ${PYTHON_BIN} -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"
ok "Python environment prepared."

log "[3/8] USB printer permissions"
echo "Choose USB access mode:"
echo "  1) Permissive (MODE=0666) — easiest (default)"
echo "  2) Group-based (GROUP=plugdev, MODE=0660) — safer (requires relogin)"
read -rp "Select [1/2]: " USB_MODE
USB_MODE=${USB_MODE:-1}
log "[3/8] Installing udev rule for USB printers (sudo)..."
UDEV_RULE_FILE="/etc/udev/rules.d/99-receiptquest-printers.rules"
if [[ "$USB_MODE" == "2" ]]; then
  UDEV_RULE_CONTENT='SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:0701??:*", GROUP="plugdev", MODE:="0660"'
  if ! getent group plugdev >/dev/null; then
    echo "Creating plugdev group (sudo)..."
    sudo groupadd -f plugdev
  fi
  if ! id -nG "$USER" | grep -q "\bplugdev\b"; then
    echo "Adding $USER to plugdev (sudo)..."
    sudo usermod -aG plugdev "$USER"
    echo "You may need to log out and back in for group changes to take effect."
  fi
else
  UDEV_RULE_CONTENT='SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:0701??:*", MODE:="0666"'
fi
echo "$UDEV_RULE_CONTENT" | sudo tee "$UDEV_RULE_FILE" >/dev/null
sudo udevadm control --reload-rules || true
sudo udevadm trigger || true
ok "udev configured. If switching groups, you may need to relogin."

log "[4/8] Creating launchers in /usr/local/bin (sudo)..."
BIN_CLI="/usr/local/bin/receiptquest"
BIN_WEB="/usr/local/bin/receiptquest-web"

sudo tee "$BIN_CLI" >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="REPLACED_AT_INSTALL"
VENV_DIR="$REPO_DIR/.venv"
if [[ -f /etc/receiptquest/env ]]; then set -a; . /etc/receiptquest/env; set +a; fi
# Ensure a usable TMPDIR for dependencies that need temp files
if [[ -z "${TMPDIR:-}" || ! -w "${TMPDIR:-/nonexistent}" ]]; then
  export TMPDIR="${HOME}/.cache/receiptquest/tmp"
  mkdir -p "$TMPDIR"
fi
exec "$VENV_DIR/bin/python" "$REPO_DIR/main.py" "$@"
EOF
sudo chmod +x "$BIN_CLI"

sudo tee "$BIN_WEB" >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="REPLACED_AT_INSTALL"
VENV_DIR="$REPO_DIR/.venv"
if [[ -f /etc/receiptquest/env ]]; then set -a; . /etc/receiptquest/env; set +a; fi
# Ensure a usable TMPDIR for dependencies that need temp files
if [[ -z "${TMPDIR:-}" || ! -w "${TMPDIR:-/nonexistent}" ]]; then
  export TMPDIR="${HOME}/.cache/receiptquest/tmp"
  mkdir -p "$TMPDIR"
fi
exec "$VENV_DIR/bin/python" "$REPO_DIR/main.py" --web "$@"
EOF
sudo chmod +x "$BIN_WEB"
sudo sed -i "s|REPLACED_AT_INSTALL|${REPO_DIR}|g" "$BIN_CLI" "$BIN_WEB"
ok "Launchers installed."

log "[5/8] Interactive setup"
read -rp "Admin username [admin]: " RQS_WEB_USER
RQS_WEB_USER=${RQS_WEB_USER:-admin}
read -rsp "Admin password (min 12 chars): " RQS_WEB_PASS; echo
if [[ ${#RQS_WEB_PASS} -lt 12 ]]; then
  echo "Password too short (minimum 12 characters required)." >&2
  exit 1
fi
read -rp "Bind host [${DEFAULT_HOST}]: " RQS_HOST
RQS_HOST=${RQS_HOST:-$DEFAULT_HOST}
read -rp "Web port [${DEFAULT_PORT}]: " RQS_PORT
RQS_PORT=${RQS_PORT:-$DEFAULT_PORT}

# Persist credentials into config file used by the app (PBKDF2 hash)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/receiptquest"
CONFIG_FILE="$CONFIG_DIR/config.json"
mkdir -p "$CONFIG_DIR"
SECRET=$("$VENV_DIR/bin/python" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)

PBKDF2_DATA=$(RQS_WEB_PASS="$RQS_WEB_PASS" "$VENV_DIR/bin/python" - <<'PY'
import hashlib, secrets, os
password = os.environ.get('RQS_WEB_PASS', '')
salt = secrets.token_bytes(32)
iterations = 200000
password_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
print(f"{salt.hex()}:{password_hash.hex()}:{iterations}")
PY
)
IFS=':' read -r SALT HASH ITERS <<< "$PBKDF2_DATA"

TMP="$CONFIG_FILE.tmp"
umask 077
printf '{\n  "RQS_WEB_USER": "%s",\n  "RQS_WEB_HASH": "%s",\n  "RQS_WEB_SALT": "%s",\n  "RQS_PBKDF2_ITERATIONS": "%s",\n  "RQS_SECRET_KEY": "%s"\n}\n' \
  "$RQS_WEB_USER" "$HASH" "$SALT" "$ITERS" "$SECRET" > "$TMP"
chmod 600 "$TMP"
mv "$TMP" "$CONFIG_FILE"

# System-wide config for services
CONFIG_DIR_SYS="/etc/receiptquest"
CONFIG_FILE_SYS="$CONFIG_DIR_SYS/config.json"
sudo mkdir -p "$CONFIG_DIR_SYS"
TMP_SYS="/tmp/receiptquest-config.json.$$"
printf '{\n  "RQS_WEB_USER": "%s",\n  "RQS_WEB_HASH": "%s",\n  "RQS_WEB_SALT": "%s",\n  "RQS_PBKDF2_ITERATIONS": "%s",\n  "RQS_SECRET_KEY": "%s"\n}\n' \
  "$RQS_WEB_USER" "$HASH" "$SALT" "$ITERS" "$SECRET" > "$TMP_SYS"
sudo install -m 600 "$TMP_SYS" "$CONFIG_FILE_SYS"
rm -f "$TMP_SYS"
sudo chown "$USER":"$USER" "$CONFIG_FILE_SYS" || true

unset RQS_WEB_PASS PBKDF2_DATA SALT HASH ITERS

# Environment file for service/wrappers convenience
ENV_DIR="/etc/receiptquest"
ENV_FILE="$ENV_DIR/env"
sudo mkdir -p "$ENV_DIR"

read -rp "Enable Secure cookies (HTTPS only)? [Y/n]: " COOKIE_SECURE
COOKIE_SECURE=$(echo "${COOKIE_SECURE:-Y}" | tr '[:lower:]' '[:upper:]')
read -rp "Enable HSTS (only with HTTPS)? [Y/n]: " ENABLE_HSTS
ENABLE_HSTS=$(echo "${ENABLE_HSTS:-Y}" | tr '[:lower:]' '[:upper:]')

sudo tee "$ENV_FILE" >/dev/null <<EOF
RQS_HOST=${RQS_HOST}
RQS_PORT=${RQS_PORT}
RQS_COOKIE_SECURE=$([[ "$COOKIE_SECURE" == "Y" ]] && echo 1 || echo 0)
RQS_HSTS=$([[ "$ENABLE_HSTS" == "Y" ]] && echo 1 || echo 0)
# Force app to use the system-wide config for consistency across users/services
RQS_CONFIG_PATH=${CONFIG_FILE_SYS}
EOF

read -rp "Install as a systemd service to run at boot? [Y/n]: " INSTALL_SERVICE
INSTALL_SERVICE=$(echo "${INSTALL_SERVICE:-Y}" | tr '[:lower:]' '[:upper:]')
if [[ "$INSTALL_SERVICE" == "Y" ]]; then
  log "[7/8] Installing systemd service (sudo)..."
  read -rp "Service user [$(id -un)]: " SERVICE_USER
  SERVICE_USER=${SERVICE_USER:-$(id -un)}
  SERVICE_FILE="/etc/systemd/system/receiptquest.service"
  sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Receipt Quest System (Web UI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${BIN_WEB}
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=3
EnvironmentFile=-/etc/receiptquest/env

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable receiptquest.service
  sudo systemctl restart receiptquest.service || sudo systemctl start receiptquest.service
  sudo chown "$SERVICE_USER":"$SERVICE_USER" "$CONFIG_FILE_SYS" || true
  echo "Service installed. Check status with: sudo systemctl status receiptquest"
else
  log "[7/8] Skipping systemd service."
fi

log "Validating environment..."
if ! "$VENV_DIR/bin/python" - <<'PY'
import escpos, usb, flask
print("python deps ok")
PY
then
  warn "Python dependencies check failed. Try rerunning the installer."
fi

if command -v receiptquest >/dev/null 2>&1; then
  if ! receiptquest -h >/dev/null 2>&1; then
    warn "Launcher 'receiptquest' did not run as expected."
  fi
else
  warn "Launcher 'receiptquest' not found in PATH."
fi

cat <<'DONE'
============================================================
 Installation complete
============================================================
Quick usage:
  - CLI: receiptquest
  - Web: receiptquest-web

Tips:
  - If the printer isn't detected, unplug/replug or run:
      sudo udevadm control --reload-rules && sudo udevadm trigger
  - To change web host/port persistently, edit /etc/receiptquest/env
  - For secure cookies over HTTPS, export RQS_COOKIE_SECURE=1
============================================================
DONE


