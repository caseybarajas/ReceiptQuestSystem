from typing import List, Optional, Tuple, Any
import textwrap
import os
import pathlib
import tempfile

# Ensure a usable temporary directory exists before importing libraries that
# rely on tempfile (e.g., python-escpos). Some minimal systems may lack /tmp.
def _ensure_temp_directory() -> None:
    # If Python can already resolve a temp dir, keep it
    try:
        _ = tempfile.gettempdir()
        return
    except Exception:
        pass

    # Try common env vars first
    for var_name in ("TMPDIR", "TEMP", "TMP"):
        val = os.getenv(var_name)
        if isinstance(val, str) and val.strip():
            try:
                path = pathlib.Path(val.strip())
                path.mkdir(parents=True, exist_ok=True)
                os.environ[var_name] = str(path)
                _ = tempfile.gettempdir()
                return
            except Exception:
                continue

    # Fallback to a user-scoped cache path
    fallback = os.path.expanduser("~/.cache/receiptquest/tmp")
    try:
        path = pathlib.Path(fallback)
        path.mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = str(path)
        _ = tempfile.gettempdir()
    except Exception:
        # Last resort: do nothing; downstream import may still fail with a clear error
        pass

_ensure_temp_directory()

try:
    # python-escpos printer (USB)
    from escpos.printer import Usb
    try:
        # Windows-only raw printing via spooler (avoids libusb requirements)
        from escpos.printer import Win32Raw  # type: ignore
    except Exception:
        Win32Raw = None  # type: ignore
except Exception as import_error:  # pragma: no cover
    raise SystemExit(
        "python-escpos is required. Install with 'pip install python-escpos pyusb'\n"
        f"Import error: {import_error}"
    )

try:
    # PyUSB for device discovery
    import usb.core  # type: ignore
    import usb.util  # type: ignore
except Exception as import_error:  # pragma: no cover
    raise SystemExit(
        "pyusb is required for USB auto-discovery. Install with 'pip install pyusb'\n"
        f"Import error: {import_error}"
    )


# Optional explicit profile; set to None to use library default (recommended)
PRINTER_PROFILE: Optional[str] = None


def _prompt_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _get_string_safely(device, index: int) -> str:
    if not index:
        return ""
    try:
        return usb.util.get_string(device, index) or ""
    except Exception:
        return ""


def _is_printer_device(device) -> bool:
    # USB class 7 is Printer
    if getattr(device, "bDeviceClass", None) == 7:
        return True
    try:
        for cfg in device:
            for intf in cfg:
                if intf.bInterfaceClass == 7:
                    return True
    except Exception:
        pass
    return False


def discover_usb_printers() -> List[Tuple[int, int, str, str]]:
    devices = []
    try:
        for dev in usb.core.find(find_all=True):  # type: ignore[attr-defined]
            if _is_printer_device(dev):
                id_vendor = int(dev.idVendor)
                id_product = int(dev.idProduct)
                manufacturer = _get_string_safely(dev, getattr(dev, "iManufacturer", 0))
                product = _get_string_safely(dev, getattr(dev, "iProduct", 0))
                devices.append((id_vendor, id_product, manufacturer, product))
    except Exception:
        return []
    return devices


def discover_windows_printers() -> List[str]:
    try:
        import win32print  # type: ignore
    except Exception:
        return []

    flags = (
        getattr(win32print, "PRINTER_ENUM_LOCAL", 2)
        | getattr(win32print, "PRINTER_ENUM_CONNECTIONS", 4)
    )

    try:
        printers = win32print.EnumPrinters(flags)
    except Exception:
        return []

    names: List[str] = []
    for entry in printers:
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            name = entry[2]
            if isinstance(name, str):
                names.append(name)
    # Deduplicate while preserving order
    seen = set()
    unique_names = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique_names.append(n)
    return unique_names


def _prompt_select_windows_printer(names: List[str]) -> Optional[str]:
    if not names:
        return None
    if len(names) == 1:
        print(f"Using Windows printer: {names[0]}")
        return names[0]
    print("Select a Windows printer:")
    for idx, name in enumerate(names, start=1):
        print(f"  {idx}. {name}")
    while True:
        sel = _prompt_input("Select a printer by number (or press Enter to cancel): ").strip()
        if not sel:
            return None
        if sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= len(names):
                return names[idx - 1]
        print("Invalid selection. Please try again.")


def _prompt_select_usb_printer(candidates: List[Tuple[int, int, str, str]]) -> Optional[Tuple[int, int]]:
    if not candidates:
        return None
    if len(candidates) == 1:
        vid, pid, manufacturer, product = candidates[0]
        print(f"Discovered printer: {manufacturer or 'Unknown'} - {product or 'Unknown'} (VID=0x{vid:04x}, PID=0x{pid:04x})")
        return (vid, pid)

    print("Multiple USB printers detected:")
    for idx, (vid, pid, manufacturer, product) in enumerate(candidates, start=1):
        label = f"{manufacturer or 'Unknown'} - {product or 'Unknown'}"
        print(f"  {idx}. {label} (VID=0x{vid:04x}, PID=0x{pid:04x})")

    while True:
        sel = _prompt_input("Select a printer by number (or press Enter to cancel): ").strip()
        if not sel:
            return None
        if sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= len(candidates):
                vid, pid, *_ = candidates[idx - 1]
                return (vid, pid)
        print("Invalid selection. Please try again.")


def select_printer_target() -> Tuple[str, Any]:
    """Prompt once and return a reusable printer target descriptor.

    Returns ('win32', printer_name) or ('usb', (vid, pid)).
    """
    import os
    if os.name == 'nt':
        names = discover_windows_printers()
        selection = _prompt_select_windows_printer(names)
        if selection:
            return ('win32', selection)
        print(
            "Windows spooler method unavailable or not selected; attempting direct USB access (libusb required)."
        )

    candidates = discover_usb_printers()
    selection_usb = _prompt_select_usb_printer(candidates)
    if selection_usb is None:
        raise SystemExit("No suitable printer selected or found.")
    return ('usb', selection_usb)


def _select_printer_target_from_env() -> Optional[Tuple[str, Any]]:
    """Select printer target based on environment variables.

    Supported environment variables:
    - RQS_PRINTER_KIND: 'win32' or 'usb'
      - If 'win32':
          - RQS_PRINTER_NAME: Windows printer name
      - If 'usb':
          - RQS_USB_VID: Vendor ID (hex like 0x0416 or decimal)
          - RQS_USB_PID: Product ID (hex like 0x5011 or decimal)
    """
    import os
    kind = (os.getenv('RQS_PRINTER_KIND') or '').strip().lower()
    if not kind:
        return None
    if kind == 'win32':
        name = os.getenv('RQS_PRINTER_NAME')
        if name:
            return ('win32', name)
        return None
    if kind == 'usb':
        vid_raw = os.getenv('RQS_USB_VID')
        pid_raw = os.getenv('RQS_USB_PID')
        if not vid_raw or not pid_raw:
            return None
        def _parse_id(value: str) -> Optional[int]:
            v = value.strip().lower()
            try:
                if v.startswith('0x'):
                    return int(v, 16)
                return int(v)
            except Exception:
                return None
        vid = _parse_id(vid_raw)
        pid = _parse_id(pid_raw)
        if isinstance(vid, int) and isinstance(pid, int):
            return ('usb', (vid, pid))
        return None
    return None


def select_printer_target_noninteractive() -> Tuple[str, Any]:
    """Select a printer target without prompting.

    Order of precedence:
    1) Environment variables (RQS_PRINTER_KIND, ...)
    2) Windows printers (first available) if on Windows
    3) USB printers (first available)
    """
    env_target = _select_printer_target_from_env()
    if env_target is not None:
        return env_target

    import os
    if os.name == 'nt':
        names = discover_windows_printers()
        if names:
            return ('win32', names[0])

    candidates = discover_usb_printers()
    if candidates:
        vid, pid, *_ = candidates[0]
        return ('usb', (vid, pid))
    raise SystemExit("No suitable printer found (non-interactive mode). Set RQS_PRINTER_* env vars or connect a printer.")


def _open_usb_printer_with_fallbacks(vid: int, pid: int) -> Any:
    """Open a USB ESC/POS printer with several fallbacks.

    Tries default, then detaching kernel driver, then autodetected endpoints and
    configurations, and finally common endpoint/interface combos.

    Additionally, validates the handle with a minimal write (ESC @) and falls
    back if I/O fails after a seemingly successful open.
    """
    errors: List[str] = []

    def _attempt_open_and_validate(**kwargs: Any) -> Any:
        inst = Usb(vid, pid, **kwargs)
        try:
            raw_fn = getattr(inst, "_raw", None)
            if callable(raw_fn):
                raw_fn(b"\x1b@")  # Initialize printer; safe no-op for most models
            else:
                # Fallback to a benign write path
                text_fn = getattr(inst, "text", None)
                if callable(text_fn):
                    text_fn("")
        except Exception as write_exc:
            try:
                close_fn = getattr(inst, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass
            raise write_exc
        return inst

    # Attempt 1: plain
    try:
        return _attempt_open_and_validate(profile=PRINTER_PROFILE)
    except Exception as exc:
        errors.append(f"default: {exc}")

    # Attempt 2: detach kernel driver if bound
    try:
        return _attempt_open_and_validate(profile=PRINTER_PROFILE, usb_args={"detach_kernel_driver": True})
    except Exception as exc:
        errors.append(f"detach_kernel_driver: {exc}")

    # Attempt 3: read descriptors to find endpoints/configs
    try:
        dev = usb.core.find(idVendor=vid, idProduct=pid)  # type: ignore[attr-defined]
    except Exception as exc:
        dev = None
        errors.append(f"usb.find: {exc}")

    if dev is not None:
        try:
            for cfg in dev:  # type: ignore[assignment]
                cfg_val = getattr(cfg, "bConfigurationValue", None) or 1
                for intf in cfg:
                    try:
                        intf_num = getattr(intf, "bInterfaceNumber", 0)
                        out_ep = None
                        in_ep = None
                        for ep in intf:
                            addr = getattr(ep, "bEndpointAddress", None)
                            if addr is None:
                                continue
                            if usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_OUT:  # type: ignore[attr-defined]
                                out_ep = addr
                            elif usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_IN:  # type: ignore[attr-defined]
                                in_ep = addr
                        if out_ep is None:
                            continue
                        try:
                            return _attempt_open_and_validate(
                                profile=PRINTER_PROFILE,
                                interface=intf_num,
                                out_ep=out_ep,
                                in_ep=in_ep,
                                usb_args={
                                    "detach_kernel_driver": True,
                                    "bConfigurationValue": cfg_val,
                                },
                            )
                        except Exception as exc:
                            errors.append(
                                f"iface {intf_num} cfg {cfg_val} out 0x{out_ep:02x} in 0x{(in_ep or 0):02x}: {exc}"
                            )
                    except Exception as exc:
                        errors.append(f"intf-scan: {exc}")
        except Exception as exc:
            errors.append(f"cfg-scan: {exc}")

    # Attempt 4: common endpoint/interface combos
    for cfg_val in (1, 2):
        for intf_num in (0, 1):
            for in_ep in (0x81, 0x82, 0x83):
                try:
                    return _attempt_open_and_validate(
                        profile=PRINTER_PROFILE,
                        interface=intf_num,
                        out_ep=0x01,
                        in_ep=in_ep,
                        usb_args={
                            "detach_kernel_driver": True,
                            "bConfigurationValue": cfg_val,
                        },
                    )
                except Exception as exc:
                    errors.append(
                        f"combo cfg {cfg_val} if {intf_num} out 0x01 in 0x{in_ep:02x}: {exc}"
                    )

    hint = (
        "Failed to open USB printer. On Linux, ensure permissions (udev rule), and that the 'usblp' kernel driver is not binding to the device. "
        "You can test temporarily with: 'sudo modprobe -r usblp' and replug, or create a udev rule like: \n"
        "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"%04x\", ATTR{idProduct}==\"%04x\", MODE=\"0666\"\n"
        "Then: 'sudo udevadm control --reload-rules && sudo udevadm trigger' and replug the printer."
    ) % (vid, pid)
    detail = "; ".join(errors[-5:])  # include last few attempts for brevity
    raise SystemExit(f"{hint}\nLast errors: {detail}")


def open_printer_from_target(target: Tuple[str, Any]) -> Any:
    kind, data = target
    if kind == 'win32':
        if Win32Raw is None:
            raise SystemExit("Win32Raw backend not available; install python-escpos with Windows support.")
        return Win32Raw(printer_name=data)
    if kind == 'usb':
        vid, pid = data
        return _open_usb_printer_with_fallbacks(vid, pid)
    raise SystemExit("Unknown printer target kind.")


def _reset_text_style(printer_instance: Any) -> None:
    printer_instance.set(align='left', bold=False, underline=0, width=1, height=1)


def _get_columns_from_profile(profile: Any) -> Optional[int]:
    if profile is None:
        return None
    try:
        if hasattr(profile, "get") and callable(profile.get):
            cols = profile.get("columns")
            if isinstance(cols, dict):
                normal = cols.get("normal")
                if isinstance(normal, int) and normal > 0:
                    return normal
            if isinstance(cols, int) and cols > 0:
                return cols
    except Exception:
        pass

    try:
        data = getattr(profile, "profile_data", None)
        if isinstance(data, dict):
            cols = data.get("columns")
            if isinstance(cols, dict):
                normal = cols.get("normal")
                if isinstance(normal, int) and normal > 0:
                    return normal
            if isinstance(cols, int) and cols > 0:
                return cols
    except Exception:
        pass

    try:
        cols = getattr(profile, "columns", None)
        if isinstance(cols, dict):
            normal = cols.get("normal")
            if isinstance(normal, int) and normal > 0:
                return normal
        if isinstance(cols, int) and cols > 0:
            return cols
    except Exception:
        pass

    return None


def get_printer_columns(printer_instance: Any, default: int = 42) -> int:
    try:
        profile = getattr(printer_instance, "profile", None)
        cols = _get_columns_from_profile(profile)
        if isinstance(cols, int) and cols > 0:
            return cols
    except Exception:
        pass
    return default


def _separator(printer_instance: Any, width: Optional[int] = None) -> None:
    if width is None:
        width = get_printer_columns(printer_instance, default=42)
    width = max(10, int(width))
    printer_instance.text("-" * width + "\n")


def _safe_feed(printer_instance: Any, lines: int = 3) -> None:
    try:
        feed_fn = getattr(printer_instance, "feed", None)
        if callable(feed_fn):
            feed_fn(lines)
        else:
            printer_instance.text("\n" * lines)
    except Exception:
        printer_instance.text("\n" * lines)


def try_print_qr(printer_instance: Any, data: str, size: int = 4) -> None:
    """Best-effort QR printing; ignored if backend/printer does not support."""
    if not data:
        return
    try:
        qr_fn = getattr(printer_instance, "qr", None)
        if callable(qr_fn):
            qr_fn(data, size=size)
            printer_instance.text("\n")
    except Exception:
        # quietly ignore QR failures
        pass


def try_beep(printer_instance: Any, count: int = 2, duration: int = 3) -> None:
    """Best-effort audible beep to capture attention; quietly ignored if unsupported.

    Some ESC/POS printers implement a `beep` method. We try a few common signatures.
    """
    try:
        beep_fn = getattr(printer_instance, "beep", None)
        if callable(beep_fn):
            try:
                beep_fn(count, duration)
                return
            except Exception:
                pass
            try:
                beep_fn()
                return
            except Exception:
                pass
    except Exception:
        pass


def print_text_document(printer_instance: Any, title: str, body: str) -> None:
    """Deprecated: prefer print_markdown_document. Kept for backward-compatibility."""
    from .markdown_renderer import print_markdown_document  # local import to avoid cycle
    title_md = (f"# {title.strip()}\n\n" if title and title.strip() else "")
    text = f"{title_md}{body or ''}"
    print_markdown_document(printer_instance, text)
