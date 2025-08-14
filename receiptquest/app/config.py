from __future__ import annotations

from typing import Dict, Tuple
import os
import json
import pathlib
import secrets
import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def _parse_env_line(line: str) -> Tuple[str, str] | None:
    try:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            return None
        if raw.lower().startswith("export "):
            raw = raw[7:].lstrip()
        if "=" not in raw:
            return None
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return key, value
    except Exception:
        return None


def load_env_from_files(override: bool = False) -> None:
    """Load environment variables from common .env locations.

    - Does not override existing vars unless override=True
    - Supports simple KEY=VALUE and export KEY=VALUE lines, with optional quotes
    """
    try:
        candidates = []
        # Explicit path wins
        explicit = os.getenv("RQS_ENV_PATH")
        if isinstance(explicit, str) and explicit.strip():
            candidates.append(explicit.strip())

        # Project root and CWD .env files
        try:
            here = pathlib.Path(__file__).resolve()
            repo_root = here.parent.parent.parent  # .../ReceiptQuestSystem
            candidates.extend([
                str(repo_root / ".env"),
                str(repo_root / ".env.local"),
                str(pathlib.Path.cwd() / ".env"),
                str(pathlib.Path.cwd() / ".env.local"),
            ])
        except Exception:
            pass

        # OS-specific conventional locations
        if os.name == "nt":
            program_data = os.getenv("ProgramData", "")
            appdata = os.getenv("APPDATA", "")
            if program_data:
                candidates.append(os.path.join(program_data, "receiptquest", "env"))
            if appdata:
                candidates.append(os.path.join(appdata, "receiptquest", "env"))
        else:
            candidates.append("/etc/receiptquest/env")

        loaded_any = False
        for path in candidates:
            try:
                if not path or not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        parsed = _parse_env_line(line)
                        if not parsed:
                            continue
                        key, value = parsed
                        if override or not (isinstance(os.getenv(key), str) and os.getenv(key) is not None and os.getenv(key) != ""):
                            os.environ[key] = value
                            loaded_any = True
                if loaded_any:
                    logger.info(f"Loaded environment from: {path}")
            except Exception as e:
                logger.debug(f"Failed to load env file {path}: {e}")
    except Exception:
        # Never fail app startup due to dotenv parsing
        pass

def _expand_user(path: str) -> str:
    try:
        return os.path.expanduser(path)
    except Exception:
        return path


def get_config_path() -> str:
    env_path = os.getenv("RQS_CONFIG_PATH")
    if isinstance(env_path, str) and env_path.strip():
        return _expand_user(env_path.strip())
    # Prefer per-user config when running as a regular user; prefer system config only for root/services
    try:
        if os.name != "nt":
            user_base = _expand_user(os.getenv("XDG_CONFIG_HOME", "~/.config").strip() or "~/.config")
            user_cfg = os.path.join(user_base, "receiptquest", "config.json")
            sys_cfg = "/etc/receiptquest/config.json"
            # Detect root
            is_root = False
            try:
                is_root = (os.geteuid() == 0)  # type: ignore[attr-defined]
            except Exception:
                is_root = False
            if is_root:
                if os.path.exists(sys_cfg) and os.access(sys_cfg, os.R_OK):
                    return sys_cfg
                return user_cfg
            # Non-root: prefer user config if present
            if os.path.exists(user_cfg) and os.access(user_cfg, os.R_OK):
                return user_cfg
            if os.path.exists(sys_cfg) and os.access(sys_cfg, os.R_OK):
                return sys_cfg
            return user_cfg
        else:
            # Windows: prefer user AppData config; fall back to ProgramData if present
            xdg = os.getenv("XDG_CONFIG_HOME")
            base = _expand_user(xdg.strip()) if isinstance(xdg, str) and xdg.strip() else _expand_user("~/.config")
            user_cfg = os.path.join(base, "receiptquest", "config.json")
            program_data = os.getenv("ProgramData")
            pd_cfg = os.path.join(program_data, "receiptquest", "config.json") if isinstance(program_data, str) and program_data.strip() else None
            if os.path.exists(user_cfg) and os.access(user_cfg, os.R_OK):
                return user_cfg
            if pd_cfg and os.path.exists(pd_cfg) and os.access(pd_cfg, os.R_OK):
                return pd_cfg
            return user_cfg
    except Exception:
        pass
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = _expand_user(xdg.strip()) if isinstance(xdg, str) and xdg.strip() else _expand_user("~/.config")
    return os.path.join(base, "receiptquest", "config.json")


def _read_json_file(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return {
                    str(k): str(v) if v is not None else ""
                    for k, v in data.items()
                    if isinstance(k, str)
                }
    except Exception:
        pass
    return {}


def _write_json_file(path: str, data: Dict[str, str]) -> None:
    directory = os.path.dirname(path)
    try:
        pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temporary file if it exists
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def generate_secret_key() -> str:
    return secrets.token_hex(32)


def _hash_password(password: str, salt_hex: str | None = None, iterations: int = 200_000) -> Tuple[str, str, int]:
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    if salt_hex is None or not isinstance(salt_hex, str) or not salt_hex:
        salt = secrets.token_bytes(16)
    else:
        salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return salt.hex(), dk.hex(), iterations


def verify_password(password: str, salt_hex: str, hash_hex: str, iterations: int = 200_000) -> bool:
    # Prevent DoS via excessive iterations
    if iterations < 1000 or iterations > 10_000_000:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except Exception:
        return False
    test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(test, expected)
def load_config() -> Tuple[Dict[str, str], bool]:
    """Return (config, needs_setup).

    Priority: environment variables override file values. If no creds are set,
    needs_setup will be True.
    """
    # Load .env and system env files first so RQS_CONFIG_PATH and creds are available
    try:
        load_env_from_files(override=False)
    except Exception:
        pass
    path = get_config_path()
    file_cfg = _read_json_file(path)

    cfg: Dict[str, str] = {
        "RQS_WEB_USER": file_cfg.get("RQS_WEB_USER", ""),
        "RQS_WEB_HASH": file_cfg.get("RQS_WEB_HASH", ""),
        "RQS_WEB_SALT": file_cfg.get("RQS_WEB_SALT", ""),
        "RQS_PBKDF2_ITERATIONS": str(file_cfg.get("RQS_PBKDF2_ITERATIONS", "200000")),
        "RQS_SECRET_KEY": file_cfg.get("RQS_SECRET_KEY", ""),
    }

    # Environment overrides (handle credentials as a group to prevent mismatches)
    # Also read from /etc/receiptquest/env (or platform equivalents)
    load_env_from_files(override=False)
    env_user = os.getenv("RQS_WEB_USER")
    env_hash = os.getenv("RQS_WEB_HASH")
    env_salt = os.getenv("RQS_WEB_SALT")
    env_iters = os.getenv("RQS_PBKDF2_ITERATIONS")
    env_secret = os.getenv("RQS_SECRET_KEY")
    env_pass = os.getenv("RQS_WEB_PASS")

    if isinstance(env_secret, str) and env_secret.strip():
        cfg["RQS_SECRET_KEY"] = env_secret.strip()

    has_env_hash = isinstance(env_hash, str) and bool(env_hash.strip())
    has_env_salt = isinstance(env_salt, str) and bool(env_salt.strip())
    has_env_user = isinstance(env_user, str) and bool(env_user.strip())

    # Env credentials handling
    # 1) If RQS_WEB_HASH + RQS_WEB_SALT provided: use them (optionally RQS_WEB_USER)
    if has_env_hash and has_env_salt:
        cfg["RQS_WEB_HASH"] = env_hash.strip()
        cfg["RQS_WEB_SALT"] = env_salt.strip()
        if has_env_user:
            cfg["RQS_WEB_USER"] = env_user.strip()
        # iterations override if present and valid
        if isinstance(env_iters, str) and env_iters.strip():
            try:
                it_override = int(env_iters.strip())
                if it_override > 0:
                    cfg["RQS_PBKDF2_ITERATIONS"] = str(it_override)
            except Exception:
                pass
    # 2) Else, if RQS_WEB_PASS + RQS_WEB_USER present: migrate from env into memory (no file write here)
    elif (isinstance(env_pass, str) and env_pass.strip()) and has_env_user:
        try:
            salt_hex, hash_hex, iters = _hash_password(env_pass.strip())
            cfg["RQS_WEB_USER"] = env_user.strip()
            cfg["RQS_WEB_HASH"] = hash_hex
            cfg["RQS_WEB_SALT"] = salt_hex
            cfg["RQS_PBKDF2_ITERATIONS"] = str(iters)
        except Exception as e:
            logger.error(f"Failed to derive hash from env password: {e}")
    else:
        # Ignore username-only env to avoid breaking auth with mismatched hashed credentials
        if has_env_user:
            logger.warning("Ignoring RQS_WEB_USER from environment without matching credentials")
    # Normalize to avoid invisible mismatches/hex parse errors
    cfg["RQS_WEB_USER"] = (cfg.get("RQS_WEB_USER") or "").strip()
    for norm_key in ("RQS_WEB_HASH", "RQS_WEB_SALT", "RQS_PBKDF2_ITERATIONS", "RQS_SECRET_KEY"):
        if isinstance(cfg.get(norm_key), str):
            cfg[norm_key] = cfg[norm_key].strip()
    
    # Migrate plaintext password to hashed fields (support file or env plaintext)
    need_hash = (not cfg.get("RQS_WEB_HASH") or not cfg.get("RQS_WEB_SALT"))
    file_pass = file_cfg.get("RQS_WEB_PASS")
    file_user = file_cfg.get("RQS_WEB_USER")
    env_pass_val = env_pass.strip() if (isinstance(env_pass, str) and env_pass.strip()) else None
    env_user_val = env_user.strip() if (isinstance(env_user, str) and env_user.strip()) else None
    if need_hash and ((file_pass and file_user) or (env_pass_val and env_user_val)):
        try:
            source_pass = file_pass if (file_pass and file_user) else env_pass_val
            source_user = file_user if (file_pass and file_user) else env_user_val
            salt_hex, hash_hex, iters = _hash_password(source_pass)
            # Keep cfg consistent (override any env user to match hashed creds)
            cfg["RQS_WEB_USER"] = (source_user or "").strip()
            cfg["RQS_WEB_HASH"] = hash_hex
            cfg["RQS_WEB_SALT"] = salt_hex
            cfg["RQS_PBKDF2_ITERATIONS"] = str(iters)
            # Attempt to persist only if we can write to the chosen config path and the source was file-based
            write_allowed = False
            try:
                write_allowed = os.access(path, os.W_OK)
            except Exception:
                write_allowed = False
            source_is_file = bool(file_pass and file_user)
            if write_allowed and source_is_file:
                new = dict(file_cfg)
                new.pop("RQS_WEB_PASS", None)
                new["RQS_WEB_USER"] = cfg["RQS_WEB_USER"]
                new["RQS_WEB_SALT"] = salt_hex
                new["RQS_WEB_HASH"] = hash_hex
                new["RQS_PBKDF2_ITERATIONS"] = str(iters)
                _write_json_file(path, new)
        except Exception as e:
            logger.error(f"Failed to migrate plaintext password to hashed format: {e}")
            # If we cannot write to the config path (likely system-wide), do not fail startup. Credentials are set in-memory.
            try:
                can_write = os.access(path, os.W_OK)
            except Exception:
                can_write = False
            if can_write:
                # Ensure plaintext password is removed from on-disk config even on failure
                try:
                    safe_config = dict(file_cfg)
                    safe_config.pop("RQS_WEB_PASS", None)
                    _write_json_file(path, safe_config)
                except Exception as write_error:
                    logger.error(f"Failed to remove plaintext password from config file: {write_error}")
                    raise RuntimeError(f"Migration failed and unable to secure config file: {write_error}") from e
                # Re-raise the original migration error
                raise RuntimeError(f"Password migration failed: {e}") from e
            else:
                logger.warning("Running with migrated credentials in memory (read-only config). Consider updating the config file with hashed credentials.")

    needs_setup = not (cfg.get("RQS_WEB_USER") and cfg.get("RQS_WEB_HASH") and cfg.get("RQS_WEB_SALT"))
    return cfg, needs_setup


def save_credentials(username: str, password: str, secret_key: str | None = None) -> None:
    path = get_config_path()
    cfg = _read_json_file(path)
    cfg["RQS_WEB_USER"] = (username or "").strip()
    salt_hex, hash_hex, iters = _hash_password(password)
    cfg["RQS_WEB_SALT"] = salt_hex
    cfg["RQS_WEB_HASH"] = hash_hex
    cfg["RQS_PBKDF2_ITERATIONS"] = str(iters)
    if not secret_key:
        secret_key = generate_secret_key()
    cfg["RQS_SECRET_KEY"] = secret_key
    _write_json_file(path, cfg)
