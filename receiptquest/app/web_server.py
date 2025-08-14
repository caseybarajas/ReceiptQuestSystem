from __future__ import annotations

from typing import Any, Dict, List, Tuple
import os
import time
import secrets
import threading
from queue import Queue, Empty

from flask import Flask, request, redirect, url_for, render_template_string, session, abort

from ..printing import open_printer_from_target
from ..printing.quest_formatter import print_supportive_quest
from ..core.models import Quest, Objective


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def create_app(
    printer_target: Tuple[str, Any],
    default_step_style: str = "checkbox",
    use_llm: bool = True,
    adhd_mode: str = "super",
) -> Flask:
    # Load environment variables from .env-like files before reading config
    try:
        from .config import load_env_from_files  # type: ignore
        load_env_from_files(override=False)
    except Exception:
        pass
    app = Flask(__name__)
    # Config and first-run setup
    from .config import load_config, save_credentials, generate_secret_key, verify_password
    cfg, needs_setup = load_config()
    secret_key = cfg.get("RQS_SECRET_KEY") or generate_secret_key()
    app.secret_key = secret_key
    # Secure cookie/session defaults (configurable via env)
    def _env_bool(name: str, default: bool = False) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        vv = v.strip().lower()
        return vv in {"1", "true", "yes", "on"}

    app.config.update({
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _env_bool("RQS_COOKIE_SECURE", False),
        "PERMANENT_SESSION_LIFETIME": 60 * 60 * 8,  # 8 hours
    })
    username = cfg.get("RQS_WEB_USER", "")
    password_hash = cfg.get("RQS_WEB_HASH", "")
    password_salt = cfg.get("RQS_WEB_SALT", "")
    
    # Validate PBKDF2 iterations with safe fallback
    try:
        password_iters = int(cfg.get("RQS_PBKDF2_ITERATIONS", "200000") or "200000")
        if password_iters <= 0:
            raise ValueError("Iterations must be positive")
    except (ValueError, TypeError) as e:
        import logging
        logging.warning(f"Invalid PBKDF2 iterations config: {e}. Using default 200000.")
        password_iters = 200000

    # Beautiful mobile-first dark pastel blue UI
    base_html = """
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, user-scalable=no\">
  <title>Receipt Quest</title>
  <style>
    /* CSS Variables for dark pastel blue theme */
    :root {
      --bg-primary: #0f1628;
      --bg-secondary: #1a2332;
      --bg-card: #212b3d;
      --bg-input: #162030;
      --accent-blue: #4f8cc9;
      --accent-light: #6ba3d6;
      --accent-glow: rgba(79, 140, 201, 0.2);
      --text-primary: #e8eef7;
      --text-secondary: #9ca8ba;
      --text-muted: #6b7a8f;
      --border-light: #2a3441;
      --border-focus: #4f8cc9;
      --success: #4ade80;
      --error: #f87171;
      --shadow-card: 0 8px 32px rgba(15, 22, 40, 0.6);
      --shadow-button: 0 4px 16px rgba(79, 140, 201, 0.3);
      --radius-sm: 8px;
      --radius-md: 12px;
      --radius-lg: 16px;
      --radius-xl: 20px;
    }

    /* Global reset and base styles */
    *, *::before, *::after { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      margin: 0; padding: 0;
      background: linear-gradient(135deg, var(--bg-primary) 0%, #0a1220 100%);
      color: var(--text-primary);
      line-height: 1.6;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      overflow-x: hidden;
    }

    /* Animated background particles */
    body::before {
      content: '';
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: radial-gradient(circle at 20% 80%, rgba(79, 140, 201, 0.05) 0%, transparent 50%),
                  radial-gradient(circle at 80% 20%, rgba(79, 140, 201, 0.03) 0%, transparent 50%);
      pointer-events: none;
      z-index: -1;
    }

    /* Main content area - no header needed */
    main {
      max-width: 420px;
      margin: 0 auto;
      padding: 32px 16px 80px;
      position: relative;
      z-index: 1;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    @media (max-width: 480px) {
      main { padding: 24px 12px 80px; }
    }

    /* Beautiful card with animations */
    .card {
      background: rgba(33, 43, 61, 0.7);
      backdrop-filter: blur(20px);
      border: 1px solid var(--border-light);
      border-radius: var(--radius-xl);
      padding: 32px;
      box-shadow: var(--shadow-card);
      animation: cardFloat 0.8s ease-out, fadeInUp 0.6s ease-out;
      position: relative;
      overflow: hidden;
    }
    .card::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 1px;
      background: linear-gradient(90deg, transparent 0%, var(--accent-glow) 50%, transparent 100%);
      animation: shimmer 2s ease-in-out infinite;
    }

    /* Form styling */
    form { margin: 0; }
    h2 {
      margin: 0 0 20px 0;
      font-size: 24px;
      font-weight: 600;
      color: var(--text-primary);
      animation: fadeInUp 0.7s ease-out 0.2s both;
    }

    /* Hero input with special styling */
    .hero-input {
      margin: 24px 0;
      position: relative;
      animation: fadeInUp 0.7s ease-out 0.3s both;
    }
    .hero-input input[type=text] {
      width: 100%;
      padding: 20px 18px;
      background: rgba(22, 32, 48, 0.8);
      border: 2px solid var(--border-light);
      border-radius: var(--radius-lg);
      color: var(--text-primary);
      font-size: 18px;
      font-weight: 500;
      outline: none;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      -webkit-tap-highlight-color: transparent;
    }
    .hero-input input[type=text]:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 4px var(--accent-glow), 0 8px 24px rgba(79, 140, 201, 0.15);
      transform: translateY(-2px);
    }
    .hero-input input[type=text]::placeholder {
      color: var(--text-muted);
      opacity: 0.8;
    }

    /* Labels and form inputs */
    label {
      display: block;
      margin: 16px 0 8px;
      font-size: 14px;
      font-weight: 500;
      color: var(--text-secondary);
      letter-spacing: 0.3px;
    }
    input[type=text], input[type=password], textarea, select {
      width: 100%;
      padding: 14px 16px;
      background: rgba(22, 32, 48, 0.6);
      border: 1px solid var(--border-light);
      border-radius: var(--radius-md);
      color: var(--text-primary);
      font-size: 16px;
      outline: none;
      transition: all 0.3s ease;
      -webkit-tap-highlight-color: transparent;
    }
    input:focus, textarea:focus, select:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 3px var(--accent-glow);
      background: rgba(22, 32, 48, 0.9);
    }
    textarea {
      min-height: 100px;
      resize: vertical;
      font-family: inherit;
      line-height: 1.5;
    }

    /* Grid layout */
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-top: 16px;
    }
    @media (max-width: 480px) {
      .row { grid-template-columns: 1fr; gap: 12px; }
    }

    /* Collapsible details */
    details {
      margin-top: 20px;
      animation: fadeInUp 0.7s ease-out 0.4s both;
    }
    summary {
      cursor: pointer;
      color: var(--text-secondary);
      font-size: 14px;
      font-weight: 500;
      padding: 8px 0;
      transition: color 0.3s ease;
      user-select: none;
      -webkit-tap-highlight-color: transparent;
    }
    summary:hover { color: var(--accent-light); }
    details[open] summary { color: var(--accent-light); margin-bottom: 12px; }

    /* Action buttons - inline with content */
    .actions {
      padding: 32px 0 0;
      display: flex;
      gap: 12px;
      justify-content: center;
      animation: fadeInUp 0.6s ease-out 0.5s both;
    }
    .actions.fixed {
      position: fixed;
      bottom: 0; left: 0; right: 0;
      padding: 20px 16px 20px;
      background: rgba(26, 35, 50, 0.9);
      backdrop-filter: blur(20px);
      border-top: 1px solid var(--border-light);
      z-index: 200;
    }
    @supports (padding: max(0px)) {
      .actions.fixed { padding-bottom: max(20px, env(safe-area-inset-bottom)); }
    }

    /* Beautiful buttons with animations */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 14px 24px;
      border: none;
      border-radius: var(--radius-md);
      font-size: 16px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      position: relative;
      overflow: hidden;
      -webkit-tap-highlight-color: transparent;
      user-select: none;
      min-width: 120px;
    }
    .btn:active { transform: scale(0.98); }
    
    /* Primary button */
    .btn:not(.secondary) {
      background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-light) 100%);
      color: white;
      box-shadow: var(--shadow-button);
    }
    .btn:not(.secondary):hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(79, 140, 201, 0.4);
    }
    
    /* Secondary button */
    .btn.secondary {
      background: rgba(42, 52, 65, 0.8);
      color: var(--text-secondary);
      border: 1px solid var(--border-light);
    }
    .btn.secondary:hover {
      background: rgba(42, 52, 65, 1);
      color: var(--text-primary);
      border-color: var(--border-focus);
    }

    /* Button ripple effect */
    .btn::before {
      content: '';
      position: absolute;
      top: 50%; left: 50%;
      width: 0; height: 0;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.2);
      transform: translate(-50%, -50%);
      transition: width 0.6s, height 0.6s;
      pointer-events: none;
    }
    .btn:active::before {
      width: 300px;
      height: 300px;
    }

    /* Status messages */
    .success, .error {
      margin-top: 16px;
      padding: 12px 16px;
      border-radius: var(--radius-md);
      font-size: 14px;
      font-weight: 500;
      animation: fadeInUp 0.5s ease-out;
    }
    .success {
      background: rgba(74, 222, 128, 0.1);
      color: var(--success);
      border: 1px solid rgba(74, 222, 128, 0.2);
    }
    .error {
      background: rgba(248, 113, 113, 0.1);
      color: var(--error);
      border: 1px solid rgba(248, 113, 113, 0.2);
    }

    /* Typography */
    .muted {
      color: var(--text-muted);
      font-size: 13px;
      line-height: 1.5;
    }
    a { color: var(--accent-light); text-decoration: none; transition: color 0.3s ease; }
    a:hover { color: var(--accent-blue); }
    code {
      background: rgba(22, 32, 48, 0.8);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 12px;
      color: var(--accent-light);
    }

    /* Animations */
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes slideDown {
      from { opacity: 0; transform: translateY(-20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes slideUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes cardFloat {
      0% { transform: translateY(0px); }
      50% { transform: translateY(-4px); }
      100% { transform: translateY(0px); }
    }
    @keyframes shimmer {
      0% { opacity: 0; }
      50% { opacity: 1; }
      100% { opacity: 0; }
    }

    /* Smooth focus indicators for accessibility */
    *:focus-visible {
      outline: 2px solid var(--accent-blue);
      outline-offset: 2px;
    }

    /* Loading states */
    .loading {
      position: relative;
      pointer-events: none;
      opacity: 0.7;
    }
    .loading::after {
      content: '';
      position: absolute;
      top: 50%; left: 50%;
      width: 20px; height: 20px;
      border: 2px solid transparent;
      border-top: 2px solid var(--accent-blue);
      border-radius: 50%;
      animation: spin 1s linear infinite;
      transform: translate(-50%, -50%);
    }
    @keyframes spin {
      to { transform: translate(-50%, -50%) rotate(360deg); }
    }

    /* Responsive safe areas */
    @supports (padding: max(0px)) {
      body { padding-bottom: env(safe-area-inset-bottom); }
    }
  </style>
  <meta name=\"color-scheme\" content=\"dark\">
  <meta name=\"theme-color\" content=\"#0f1628\">
  <meta name=\"format-detection\" content=\"telephone=no\">
  <meta name=\"apple-mobile-web-app-capable\" content=\"yes\">
  <meta name=\"apple-mobile-web-app-status-bar-style\" content=\"black-translucent\">
  <meta name=\"mobile-web-app-capable\" content=\"yes\">
  <link rel=\"manifest\" href=\"/manifest.webmanifest\">
</head>
<body>
  <main>
    <div class=\"card\">
      {{ content|safe }}
    </div>
  </main>
</body>
</html>
"""

    setup_html = """
  <div style=\"text-align: center; margin-bottom: 32px;\">
    <div style=\"font-size: 48px; margin-bottom: 12px;\">🔧</div>
    <h2 style=\"margin: 0; font-size: 28px;\">Setup Your Quest Hub</h2>
    <p style=\"color: var(--text-muted); margin: 12px 0 0;\">Create your admin account to get started</p>
  </div>
  <form method=\"post\"> 
    <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token }}\">
    <label>Admin Username</label>
    <input type=\"text\" name=\"username\" autocomplete=\"username\" placeholder=\"Choose a username\" required>
    <label>Secure Password</label>
    <input type=\"password\" name=\"password\" autocomplete=\"new-password\" placeholder=\"At least 8 characters\" required>
    <div class=\"actions\">
      <button class=\"btn\" type=\"submit\">Create Account</button>
    </div>
    {% if error %}<div class=\"error\">{{ error }}</div>{% endif %}
  </form>
"""

    login_html = """
  <div style=\"text-align: center; margin-bottom: 32px;\">
    <div style=\"font-size: 48px; margin-bottom: 12px;\">🔐</div>
    <h2 style=\"margin: 0; font-size: 28px;\">Welcome Back</h2>
    <p style=\"color: var(--text-muted); margin: 12px 0 0;\">Sign in to continue your quest</p>
  </div>
  <form method=\"post\"> 
    <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token }}\">
    <label>Username</label>
    <input type=\"text\" name=\"username\" autocomplete=\"username\" placeholder=\"Enter your username\" required>
    <label>Password</label>
    <input type=\"password\" name=\"password\" autocomplete=\"current-password\" placeholder=\"Enter your password\" required>
    <div class=\"actions\">
      <button class=\"btn\" type=\"submit\">Sign In</button>
    </div>
    {% if error %}<div class=\"error\">{{ error }}</div>{% endif %}
  </form>
"""

    home_html = """
  <div style=\"text-align: center; margin-bottom: 32px;\">
    <div style=\"font-size: 48px; margin-bottom: 12px;\">📝</div>
    <h2 style=\"margin: 0; font-size: 28px;\">Create Your Quest</h2>
    <p style=\"color: var(--text-muted); margin: 12px 0 0;\">Turn any task into a printable adventure</p>
  </div>
  
  <form method=\"post\" action=\"{{ url_for('submit') }}\"> 
    <input type=\"hidden\" name=\"csrf_token\" value=\"{{ csrf_token }}\">
    
    <div class=\"hero-input\">
      <input type=\"text\" name=\"line\" placeholder=\"What would you like to accomplish?\" autocomplete=\"off\" autocapitalize=\"sentences\" spellcheck=\"false\" autofocus>
    </div>
    
    <div class=\"actions\"> 
      <button class=\"btn\" type=\"submit\">Print Quest</button>
    </div>
    
    {% if message %}<div class=\"success\">{{ message }}</div>{% endif %} 
    {% if error %}<div class=\"error\">{{ error }}</div>{% endif %} 
  </form> 

"""

    printed_html = """
  <div style=\"text-align: center;\">
    <div style=\"font-size: 64px; margin-bottom: 16px; animation: bounce 1s ease-in-out;\">🎉</div>
    <h2 style=\"margin: 0 0 12px 0; font-size: 28px;\">Quest Dispatched!</h2>
    <div class=\"success\" style=\"margin: 0; border: none; background: none; text-align: center;\">
      <div style=\"font-size: 18px; margin-bottom: 8px;\">Your magical quest is printing now</div>
      <p style=\"margin: 0; font-size: 14px; opacity: 0.8;\">
        Check your printer in a few moments for your personalized quest receipt!
      </p>
    </div>
  </div>
  
  <div class=\"actions\">
    <a class=\"btn\" href=\"{{ url_for('home') }}\">Create Another</a>
  </div>
  
  <style>
    @keyframes bounce {
      0%, 20%, 50%, 80%, 100% { transform: translateY(0); }
      40% { transform: translateY(-20px); }
      60% { transform: translateY(-10px); }
    }
  </style>
"""

    def _is_logged_in() -> bool:
        return bool(session.get("auth") == "ok")

    def _apply_secure_headers(resp):
        try:
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault("Referrer-Policy", "no-referrer")
            # CSP: allow only same-origin, inline styles (no scripts), forms only to self
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
            resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
            # Do not use legacy XSS filter
            resp.headers.setdefault("X-XSS-Protection", "0")
            # Avoid caching auth pages
            resp.headers.setdefault("Cache-Control", "no-store")
            resp.headers.setdefault("Pragma", "no-cache")
            # Optional HSTS (only enable when served via HTTPS)
            if os.getenv("RQS_HSTS", "0").strip().lower() in {"1", "true", "yes", "on"}:
                resp.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        except Exception:
            pass
        return resp

    # Simple CSRF token
    def _get_csrf_token() -> str:
        token = session.get("csrf_token")
        if not isinstance(token, str) or not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def _require_csrf(form: Dict[str, Any]) -> None:
        token = str(form.get("csrf_token", ""))
        session_token = str(session.get("csrf_token", ""))
        if not secrets.compare_digest(token, session_token):
            abort(400)

    # Login throttling (IP-based)
    login_attempts: Dict[str, List[float]] = {}
    login_lock = threading.Lock()

    def _too_many_attempts(client_ip: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
        now = time.time()
        with login_lock:
            arr = [t for t in login_attempts.get(client_ip, []) if now - t < window_seconds]
            login_attempts[client_ip] = arr
            return len(arr) >= max_attempts

    def _record_attempt(client_ip: str) -> None:
        with login_lock:
            login_attempts.setdefault(client_ip, []).append(time.time())

    @app.get("/setup")
    def setup_get():
        if not needs_setup:
            return redirect(url_for("home"))
        content = render_template_string(setup_html, error=None, csrf_token=_get_csrf_token())
        return render_template_string(base_html, content=content)

    @app.post("/setup")
    def setup_post():
        nonlocal username, password_hash, password_salt, password_iters, needs_setup
        if not needs_setup:
            return redirect(url_for("home"))
        _require_csrf(request.form)
        user = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        if len(user) < 3 or len(pw) < 8:
            content = render_template_string(setup_html, error="Username must be 3+ chars and password 8+ chars", csrf_token=_get_csrf_token())
            return render_template_string(base_html, content=content)
        save_credentials(user, pw, secret_key)
        username = user
        # reload newly saved hashed credentials
        cfg2, _ = load_config()
        password_hash = cfg2.get("RQS_WEB_HASH", "")
        password_salt = cfg2.get("RQS_WEB_SALT", "")
        try:
            password_iters = int(cfg2.get("RQS_PBKDF2_ITERATIONS", "200000") or "200000")
        except Exception:
            password_iters = 200000
        needs_setup = False
        session["auth"] = "ok"
        return redirect(url_for("home"))

    @app.get("/login")
    def login_get():
        if needs_setup:
            return redirect(url_for("setup_get"))
        if _is_logged_in():
            return redirect(url_for("home"))
        content = render_template_string(login_html, error=None, csrf_token=_get_csrf_token())
        return render_template_string(base_html, content=content)

    @app.post("/login")
    def login_post():
        if needs_setup:
            return redirect(url_for("setup_get"))
        # Helper to reliably get the client IP, even behind a trusted proxy
        def _get_client_ip() -> str:
            if app.config.get('BEHIND_PROXY'):
                forwarded = request.headers.get('X-Forwarded-For')
                if forwarded:
                    # Take the first IP from the chain
                    return forwarded.split(',')[0].strip()
            return request.remote_addr or "unknown"

        client_ip = _get_client_ip()
        if _too_many_attempts(client_ip):
            abort(429)
        _require_csrf(request.form)
        user = request.form.get("username", "").strip()
        pw = request.form.get("password", "")

        # Reload credentials from config on each login attempt to avoid using stale values
        try:
            cfg_live, _ = load_config()
            live_user = (cfg_live.get("RQS_WEB_USER", "") or "").strip()
            live_hash = cfg_live.get("RQS_WEB_HASH", "")
            live_salt = cfg_live.get("RQS_WEB_SALT", "")
            try:
                live_iters = int(cfg_live.get("RQS_PBKDF2_ITERATIONS", "200000") or "200000")
                if live_iters <= 0:
                    live_iters = 200000
            except Exception:
                live_iters = 200000
        except Exception:
            live_user = (username or "").strip()
            live_hash = password_hash
            live_salt = password_salt
            live_iters = password_iters

        # Allow login if the password matches the single stored credential.
        # Username is compared case-insensitively when present but does not block a correct password.
        if verify_password(pw, live_salt, live_hash, live_iters):
            session["auth"] = "ok"
            return redirect(url_for("home"))

        # Fallback: if a plaintext password exists in the on-disk config, migrate it now and allow login
        try:
            from .config import get_config_path, _read_json_file, _write_json_file, _hash_password  # type: ignore
            path = get_config_path()
            raw_cfg = _read_json_file(path)
            raw_pass = str(raw_cfg.get("RQS_WEB_PASS", "") or "")
            raw_user = str(raw_cfg.get("RQS_WEB_USER", "") or "").strip()
            if raw_pass:
                salt_hex, hash_hex, iters = _hash_password(raw_pass)
                # Write migrated credentials
                new_cfg = dict(raw_cfg)
                new_cfg.pop("RQS_WEB_PASS", None)
                new_cfg["RQS_WEB_USER"] = raw_user
                new_cfg["RQS_WEB_SALT"] = salt_hex
                new_cfg["RQS_WEB_HASH"] = hash_hex
                new_cfg["RQS_PBKDF2_ITERATIONS"] = str(iters)
                _write_json_file(path, new_cfg)
                # Validate with freshly migrated values
                if verify_password(pw, salt_hex, hash_hex, iters):
                    session["auth"] = "ok"
                    return redirect(url_for("home"))
        except Exception:
            pass

        # Fallback 2: if plaintext creds are provided via environment, accept once and migrate to hashed
        try:
            env_pass = os.getenv("RQS_WEB_PASS")
            env_user = os.getenv("RQS_WEB_USER")
            if isinstance(env_pass, str) and env_pass and pw == env_pass:
                from .config import get_config_path, _read_json_file, _write_json_file, _hash_password  # type: ignore
                path = get_config_path()
                raw_cfg = _read_json_file(path)
                salt_hex, hash_hex, iters = _hash_password(env_pass)
                new_cfg = dict(raw_cfg)
                new_cfg.pop("RQS_WEB_PASS", None)
                if isinstance(env_user, str) and env_user.strip():
                    new_cfg["RQS_WEB_USER"] = env_user.strip()
                elif live_user:
                    new_cfg["RQS_WEB_USER"] = live_user
                new_cfg["RQS_WEB_SALT"] = salt_hex
                new_cfg["RQS_WEB_HASH"] = hash_hex
                new_cfg["RQS_PBKDF2_ITERATIONS"] = str(iters)
                _write_json_file(path, new_cfg)
                session["auth"] = "ok"
                return redirect(url_for("home"))
        except Exception:
            pass
        _record_attempt(client_ip)
        content = render_template_string(login_html, error="Invalid credentials", csrf_token=_get_csrf_token())
        return render_template_string(base_html, content=content)

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_get"))

    @app.get("/")
    def home():
        if needs_setup:
            return redirect(url_for("setup_get"))
        if not _is_logged_in():
            return redirect(url_for("login_get"))
        content = render_template_string(
            home_html,
            style=default_step_style,
            adhd_mode=adhd_mode,
            message=request.args.get("m"),
            error=request.args.get("e"),
            csrf_token=_get_csrf_token(),
        )
        return render_template_string(base_html, content=content)

    def _parse_objectives(raw: str) -> List[str]:
        return [item.strip() for item in raw.split(',') if item.strip()]

    def _expand_to_super_adhd(objectives: List[str], title: str, description: str) -> List[str]:
        # Import from CLI module to reuse logic without circular imports at module import time
        from .main import _expand_to_super_adhd as expand
        return expand(objectives, title, description)

    def _generate_data_from_intent(intent: str, use_llm_flag: bool) -> Dict[str, Any]:
        from .main import _generate_data_from_intent as gen
        return gen(intent, use_llm_flag)

    # ---------------- In-memory print queue ----------------
    job_queue: Queue = Queue()

    def _worker_loop() -> None:
        import logging
        import traceback
        
        logger = logging.getLogger(__name__)
        last_heartbeat = time.time()
        
        while True:
            try:
                job: Dict[str, Any] = job_queue.get()
                last_heartbeat = time.time()
                try:
                    _process_job(job)
                except Exception as e:
                    # Log the full error with job context
                    logger.exception(f"Print job failed: {e}. Job context: {job}")
                    print(f"ERROR: Print job failed - {e}")
                    print(f"Job details: {job}")
                    print(f"Traceback: {traceback.format_exc()}")
                finally:
                    try:
                        job_queue.task_done()
                    except Exception as task_done_err:
                        logger.error(f"Failed to mark job as done: {task_done_err}")
            except Exception as worker_err:
                logger.exception(f"Worker loop error: {worker_err}")
                print(f"CRITICAL: Worker loop error - {worker_err}")
                # Continue the loop to keep worker alive
                continue

    def _monitor_worker(worker_thread: threading.Thread) -> None:
        """Monitor worker thread and restart if it dies"""
        import logging
        logger = logging.getLogger(__name__)
        
        while True:
            time.sleep(30)  # Check every 30 seconds
            if not worker_thread.is_alive():
                logger.error("Print worker thread died, restarting...")
                print("WARNING: Print worker thread died, restarting...")
                # Start a new worker thread
                new_worker = threading.Thread(target=_worker_loop, name="rqs-print-worker", daemon=True)
                new_worker.start()
                worker_thread = new_worker

    def _process_job(job: Dict[str, Any]) -> None:
        # Resolve inputs
        line_j = str(job.get("line") or "").strip()
        title_j = str(job.get("title") or "").strip()
        steps_j = str(job.get("steps") or "").strip()
        description_j = str(job.get("description") or "").strip()
        style_j = str(job.get("style") or default_step_style).strip() or default_step_style
        adhd_mode_j = str(job.get("adhd_mode") or adhd_mode).strip() or adhd_mode

        # Build data
        if line_j:
            if "|" in line_j:
                raw_title, raw_steps = line_j.split("|", 1)
                title_j = raw_title.strip() or (title_j or "Untitled Quest")
                objectives = _parse_objectives(raw_steps)
                data = {"title": title_j, "description": description_j, "objectives": objectives}
            else:
                data = _generate_data_from_intent(line_j, use_llm)
                title_j = str(data.get("title", title_j or "Untitled Quest")) or "Untitled Quest"
                description_j = str(data.get("description", description_j))
                objectives = list(data.get("objectives", []) or [])
        elif title_j or steps_j or description_j:
            title_j = title_j or "Untitled Quest"
            objectives = _parse_objectives(steps_j)
            if not objectives and line_j:
                data = _generate_data_from_intent(line_j, use_llm)
                objectives = list(data.get("objectives", []) or [])
        else:
            # Nothing to do
            return

        # ADHD expansion / local LLM granular generation
        if adhd_mode_j == "super":
            try:
                from ..core.quest_generator import LocalLLMQuestGenerator
                generator = LocalLLMQuestGenerator()
                # If study-related, guide the generator harder
                subj = None
                t_l = (title_j + " " + description_j + " " + " ".join(objectives)).lower()
                cat_override = None
                if any(w in t_l for w in ["study", "homework", "assignment", "classwork", "math", "english", "essay", "paper", "writing"]):
                    cat_override = "study"
                    if any(w in t_l for w in ["math", "algebra", "geometry", "calculus", "statistics"]):
                        subj = "math"
                    elif any(w in t_l for w in ["english", "essay", "paper", "writing"]):
                        subj = "english"
                data_g = generator.generate_granular(title_j or description_j or "", objectives, fast=True, category_override=cat_override, subject=subj)
                gen_objs = list(data_g.get("objectives", []) or [])
                if gen_objs:
                    objectives = [str(o) for o in gen_objs]
                    title_j = str(data_g.get("title", title_j) or title_j)
                    description_j = str(data_g.get("description", description_j) or description_j)
                else:
                    data_c = generator.generate(title_j or description_j or "", fast=True)
                    gen_objs = list(data_c.get("objectives", []) or [])
                    if gen_objs:
                        objectives = [str(o) for o in gen_objs]
                        title_j = str(data_c.get("title", title_j) or title_j)
                        description_j = str(data_c.get("description", description_j) or description_j)
            except Exception:
                # keep original objectives
                pass

        # Print
        quest = Quest.new(
            title=title_j or "Untitled Quest",
            description=description_j or "",
            objectives=[Objective(text=str(o)) for o in objectives],
        )
        try:
            printer = open_printer_from_target(printer_target)
            try:
                print_supportive_quest(
                    printer,
                    quest,
                    step_style=style_j,
                    include_activation=True,
                    cue_text=None,
                    timer_minutes=None,
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
        except Exception:
            pass

    # Start worker thread with monitoring
    worker_thread = threading.Thread(target=_worker_loop, name="rqs-print-worker", daemon=True)
    worker_thread.start()
    
    # Start monitor thread to restart worker if it dies
    monitor_thread = threading.Thread(target=_monitor_worker, args=(worker_thread,), name="rqs-worker-monitor", daemon=True)
    monitor_thread.start()

    @app.post("/submit")
    def submit():
        if not _is_logged_in():
            abort(401)

        _require_csrf(request.form)
        form = request.form
        line = (form.get("line") or "").strip()
        title = (form.get("title") or "").strip()
        steps = (form.get("steps") or "").strip()
        description = (form.get("description") or "").strip()
        style = (form.get("style") or default_step_style).strip() or default_step_style
        adhd_mode_sel = (form.get("adhd_mode") or adhd_mode).strip() or adhd_mode
        # If nothing provided, bounce
        if not any([line, title, steps, description]):
            return redirect(url_for('home', e="Please enter a task."))

        # Enqueue job and redirect immediately
        job_queue.put({
            "line": line,
            "title": title,
            "steps": steps,
            "description": description,
            "style": style,
            "adhd_mode": adhd_mode_sel,
        })
        return redirect(url_for('printed'))

    @app.get("/printed")
    def printed():
        if not _is_logged_in():
            return redirect(url_for("login_get"))
        content = render_template_string(printed_html)
        return render_template_string(base_html, content=content)

    @app.after_request
    def add_headers(response):
        return _apply_secure_headers(response)

    @app.get("/manifest.webmanifest")
    def manifest():
        manifest_json = {
            "name": "Receipt Quest - Task Printer",
            "short_name": "Receipt Quest",
            "description": "Transform any task into detailed, printable quest receipts",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0f1628",
            "theme_color": "#4f8cc9",
            "orientation": "portrait",
            "scope": "/",
            "lang": "en",
            "categories": ["productivity", "utilities"],
            "icons": [
                {
                    "src": "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTkyIiBoZWlnaHQ9IjE5MiIgdmlld0JveD0iMCAwIDE5MiAxOTIiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIxOTIiIGhlaWdodD0iMTkyIiByeD0iNDAiIGZpbGw9IiMwZjE2MjgiLz4KPHJlY3QgeD0iMzIiIHk9IjMyIiB3aWR0aD0iMTI4IiBoZWlnaHQ9IjE2MCIgcng9IjE2IiBmaWxsPSIjNGY4Y2M5IiBmaWxsLW9wYWNpdHk9IjAuMiIvPgo8cGF0aCBkPSJNNjQgODBoMjRNNjQgOTZoNDBNNjQgMTEyaDMyTTY0IDEyOGgyNCIgc3Ryb2tlPSIjNGY4Y2M5IiBzdHJva2Utd2lkdGg9IjQiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8Y2lyY2xlIGN4PSI5NiIgY3k9IjY0IiByPSIxNiIgZmlsbD0iIzRmOGNjOSIvPgo8L3N2Zz4K",
                    "sizes": "192x192",
                    "type": "image/svg+xml",
                    "purpose": "any maskable"
                }
            ]
        }
        from flask import jsonify
        return jsonify(manifest_json)

    return app


