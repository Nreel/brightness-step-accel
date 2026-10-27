#!/usr/bin/env python3
"""Fn Keys Accel.

A small GTK4 GUI plus an evdev daemon that makes the brightness step grow when
the brightness keys are tapped rapidly. Works on X11 and Wayland, independent of
the desktop environment.

Usage:
    python3 app.py            # Open the configuration GUI
    python3 app.py --daemon   # Run the background daemon
"""

import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import evdev

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

CONFIG_DIR = Path.home() / ".config" / "fn-keys-accel"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOCK_FILE = CONFIG_DIR / "daemon.lock"
AUTOSTART_FILE = (
    Path.home() / ".config" / "autostart" / "fn-keys-accel.desktop"
)

DEFAULT_CONFIG = {
    "base_step": 2,
    "max_step": 20,
    "window_ms": 200,
    "hold_accel": True,
    "brightness_acceleration": True,
    "sound_acceleration": False,
}

UP_KEY = evdev.ecodes.KEY_BRIGHTNESSUP
DOWN_KEY = evdev.ecodes.KEY_BRIGHTNESSDOWN
BRIGHTNESS_KEYS = (UP_KEY, DOWN_KEY)

VOLUME_UP_KEY = evdev.ecodes.KEY_VOLUMEUP
VOLUME_DOWN_KEY = evdev.ecodes.KEY_VOLUMEDOWN
SOUND_KEYS = (VOLUME_UP_KEY, VOLUME_DOWN_KEY)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


# ---------------------------------------------------------------------------
# Brightness backend
# ---------------------------------------------------------------------------
def _sysfs_brightness_path():
    base = Path("/sys/class/backlight")
    if not base.exists():
        return None
    for device in base.iterdir():
        brightness = device / "brightness"
        max_brightness = device / "max_brightness"
        if brightness.exists() and max_brightness.exists():
            return device
    return None


def _write_sysfs(device, delta_percent):
    """Adjust brightness directly through sysfs. Requires write permission."""
    max_brightness = int((device / "max_brightness").read_text().strip())
    current = int((device / "brightness").read_text().strip())
    delta = int(max_brightness * delta_percent / 100)
    target = max(0, min(max_brightness, current + delta))
    if target == current:
        return False
    try:
        (device / "brightness").write_text(str(target))
        return True
    except PermissionError:
        return False


KDE_BRIGHTNESS_SERVICE = "org.kde.Solid.PowerManagement"
KDE_BRIGHTNESS_OBJECT = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
KDE_BRIGHTNESS_INTERFACE = "org.kde.Solid.PowerManagement.Actions.BrightnessControl"


def _kde_busctl_call(method, signature=None, *args):
    """Call a method on KDE's brightness DBus interface via busctl.

    Returns an int for getters, ``True`` for successful setters, or ``None``.
    """
    if not shutil.which("busctl"):
        return None
    cmd = [
        "busctl", "--user", "call",
        KDE_BRIGHTNESS_SERVICE,
        KDE_BRIGHTNESS_OBJECT,
        KDE_BRIGHTNESS_INTERFACE,
        method,
    ]
    if signature:
        cmd.append(signature)
        cmd.extend(str(a) for a in args)
    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    if signature:
        return True
    try:
        return int(result.stdout.strip().split()[-1])
    except (ValueError, IndexError):
        return None


def _kde_get_brightness():
    """Return ``(current, minimum, maximum)`` from KDE, or ``None``."""
    current = _kde_busctl_call("brightness")
    if current is None:
        return None
    minimum = _kde_busctl_call("brightnessMin")
    if minimum is None:
        minimum = 0
    maximum = _kde_busctl_call("brightnessMax")
    if maximum is None:
        return None
    return current, minimum, maximum


def _kde_set_brightness(value):
    """Set absolute brightness through KDE's DBus interface."""
    return _kde_busctl_call("setBrightness", "i", value) is True


def change_brightness(step, direction):
    """Increase or decrease brightness by ``step`` percent."""
    delta = step if direction > 0 else -step

    # Prefer KDE's own brightness control so its OSD and slider stay in sync.
    state = _kde_get_brightness()
    if state is not None:
        current, minimum, maximum = state
        delta_abs = int(maximum * delta / 100)
        target = max(minimum, min(maximum, current + delta_abs))
        if target != current and _kde_set_brightness(target):
            return True

    if shutil.which("brightnessctl"):
        sign = "+" if direction > 0 else "-"
        result = subprocess.run(
            ["brightnessctl", "set", f"{step}%{sign}"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return True

    device = _sysfs_brightness_path()
    if device and _write_sysfs(device, delta):
        return True

    # Last resort: try pkexec to write sysfs with elevated privileges.
    if device and shutil.which("pkexec"):
        max_brightness = int((device / "max_brightness").read_text().strip())
        current = int((device / "brightness").read_text().strip())
        delta_abs = int(max_brightness * delta / 100)
        target = max(0, min(max_brightness, current + delta_abs))
        if target == current:
            return True
        script = f"echo {target} > {device}/brightness"
        try:
            result = subprocess.run(["pkexec", "sh", "-c", script], check=False)
            return result.returncode == 0
        except Exception:
            pass

    return False


def change_volume(step, direction):
    """Increase or decrease volume by ``step`` percent."""
    sign = "+" if direction > 0 else "-"
    
    # Prefer PulseAudio/PipeWire via pactl
    try:
        result = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{step}%"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    # Fallback to ALSA amixer
    try:
        result = subprocess.run(
            ["amixer", "-D", "pulse", "sset", "Master", f"{step}%{sign}"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    return False


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------
def find_devices():
    devices = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            # Skip virtual devices this daemon creates, otherwise a restart
            # while stale devices exist would grab its own output.
            if dev.name.startswith("accel-"):
                continue
            caps = dev.capabilities(verbose=False)
            keys = caps.get(evdev.ecodes.EV_KEY, [])
            if UP_KEY in keys or DOWN_KEY in keys or VOLUME_UP_KEY in keys or VOLUME_DOWN_KEY in keys:
                devices.append(dev)
        except PermissionError:
            pass
        except Exception:
            pass
    return devices


def _daemon_already_running():
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError):
        LOCK_FILE.unlink(missing_ok=True)
        return False


def run_daemon():
    if _daemon_already_running():
        print("Daemon already running.", file=sys.stderr)
        sys.exit(0)

    config = load_config()
    devices = find_devices()
    if not devices:
        print(
            "No keyboards with brightness keys found. "
            "Ensure you are in the 'input' group and re-login.",
            file=sys.stderr,
        )
        sys.exit(1)

    dev_map = {}
    selector = selectors.DefaultSelector()
    running = True

    def _handle_signal(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        for dev in devices:
            dev.grab()
            virtual = evdev.UInput.from_device(dev, name=f"accel-{dev.name}")
            dev_map[dev.path] = virtual
            selector.register(dev, selectors.EVENT_READ)
    except PermissionError:
        print(
            "Permission denied while grabbing input devices. "
            "Add your user to the 'input' group and re-login.",
            file=sys.stderr,
        )
        for dev in dev_map:
            try:
                dev.ungrab()
            except Exception:
                pass
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to initialize devices: {exc}", file=sys.stderr)
        sys.exit(1)

    last_press = {UP_KEY: 0.0, DOWN_KEY: 0.0, VOLUME_UP_KEY: 0.0, VOLUME_DOWN_KEY: 0.0}
    press_count = {UP_KEY: 0, DOWN_KEY: 0, VOLUME_UP_KEY: 0, VOLUME_DOWN_KEY: 0}
    held = {}  # (dev.path, code) -> {"due": ms, "kernel_repeat": bool}
    repeat_delay_ms = 400
    repeat_interval_ms = 40
    hold_accel = config.get("hold_accel", True)

    def _apply_press(code, is_repeat=False):
        now = time.monotonic() * 1000.0
        if not is_repeat and now - last_press[code] > config["window_ms"]:
            press_count[code] = 0
        press_count[code] += 1
        last_press[code] = now

        if code in BRIGHTNESS_KEYS:
            # Apply acceleration only if enabled for brightness
            if config.get("brightness_acceleration", True):
                step = min(config["base_step"] * press_count[code], config["max_step"])
            else:
                step = config["base_step"]
            direction = 1 if code == UP_KEY else -1
            change_brightness(step, direction)
        elif code in SOUND_KEYS:
            # Apply acceleration only if enabled for sound
            if config.get("sound_acceleration", False):
                step = min(config["base_step"] * press_count[code], config["max_step"])
            else:
                step = config["base_step"]
            direction = 1 if code == VOLUME_UP_KEY else -1
            change_volume(step, direction)

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))

    try:
        while running:
            now_ms = time.monotonic() * 1000.0
            next_due = min(
                (state["due"] for state in held.values() if not state["kernel_repeat"]),
                default=None,
            )
            if next_due is not None:
                timeout = max(0.01, min(0.5, (next_due - now_ms) / 1000.0))
            else:
                timeout = 0.5
            for key, _mask in selector.select(timeout=timeout):
                dev = key.fileobj
                virtual = dev_map[dev.path]
                for event in dev.read():
                    if event.type == evdev.ecodes.EV_KEY and (event.code in BRIGHTNESS_KEYS or event.code in SOUND_KEYS):
                        code = event.code
                        # value 0 = key up, 1 = key down, 2 = key repeat
                        if event.value == 1:
                            _apply_press(code, is_repeat=False)
                            if hold_accel:
                                held[(dev.path, code)] = {
                                    "due": time.monotonic() * 1000.0 + repeat_delay_ms,
                                    "kernel_repeat": False,
                                }
                        elif event.value == 2:
                            if hold_accel:
                                _apply_press(code, is_repeat=True)
                                key_tuple = (dev.path, code)
                                if key_tuple in held:
                                    held[key_tuple]["kernel_repeat"] = True
                        elif event.value == 0:
                            held.pop((dev.path, code), None)
                        # Swallow the brightness key so the desktop does not also act.
                        continue
                    # Forward every other event so the keyboard keeps working.
                    # The physical device's EV_SYN event is forwarded too, so no
                    # explicit syn() call is required here.
                    virtual.write_event(event)
            # Generate our own key repeat when the device does not.
            now_ms = time.monotonic() * 1000.0
            for key_tuple, state in list(held.items()):
                if state["kernel_repeat"]:
                    continue
                if now_ms >= state["due"]:
                    _apply_press(key_tuple[1], is_repeat=True)
                    state["due"] = now_ms + repeat_interval_ms
    except Exception as exc:
        print(f"Daemon error: {exc}", file=sys.stderr)
    finally:
        for dev in devices:
            try:
                dev.ungrab()
            except Exception:
                pass
        for virtual in dev_map.values():
            try:
                virtual.close()
            except Exception:
                pass
        selector.close()
        LOCK_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Fn Keys Accel")
        self.set_default_size(420, 360)
        self.config = load_config()
        self._build_ui()

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        frame = Gtk.Frame(label="Settings")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)
        inner.set_margin_start(8)
        inner.set_margin_end(8)
        frame.set_child(inner)
        outer.append(frame)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(Gtk.Label(label="Base step (%):", xalign=0, hexpand=True))
        self.base_spin = Gtk.SpinButton.new_with_range(1, 10, 1)
        self.base_spin.set_value(self.config["base_step"])
        row.append(self.base_spin)
        inner.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(Gtk.Label(label="Max step (%):", xalign=0, hexpand=True))
        self.max_spin = Gtk.SpinButton.new_with_range(1, 50, 1)
        self.max_spin.set_value(self.config["max_step"])
        row.append(self.max_spin)
        inner.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(Gtk.Label(label="Rapid tap window (ms):", xalign=0, hexpand=True))
        self.window_spin = Gtk.SpinButton.new_with_range(50, 1000, 10)
        self.window_spin.set_value(self.config["window_ms"])
        row.append(self.window_spin)
        inner.append(row)

        self.hold_check = Gtk.CheckButton(label="Accelerate while holding")
        self.hold_check.set_active(self.config.get("hold_accel", True))
        outer.append(self.hold_check)

        self.brightness_accel_check = Gtk.CheckButton(label="Enable brightness acceleration")
        self.brightness_accel_check.set_active(self.config.get("brightness_acceleration", True))
        outer.append(self.brightness_accel_check)

        self.sound_accel_check = Gtk.CheckButton(label="Enable sound acceleration")
        self.sound_accel_check.set_active(self.config.get("sound_acceleration", False))
        outer.append(self.sound_accel_check)

        autostart_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_btn = Gtk.Button(label="Add to startup")
        add_btn.connect("clicked", self._on_add_autostart)
        remove_btn = Gtk.Button(label="Remove from startup")
        remove_btn.connect("clicked", self._on_remove_autostart)
        autostart_box.append(add_btn)
        autostart_box.append(remove_btn)
        outer.append(autostart_box)

        self.autostart_status = Gtk.Label(xalign=0)
        outer.append(self.autostart_status)
        self._update_autostart_status()

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="Save & Restart")
        save_btn.connect("clicked", self._on_save)
        stop_btn = Gtk.Button(label="Stop")
        stop_btn.connect("clicked", self._on_stop)
        quit_btn = Gtk.Button(label="Quit")
        quit_btn.connect("clicked", self._on_quit)
        buttons.append(save_btn)
        buttons.append(stop_btn)
        buttons.append(quit_btn)
        outer.append(buttons)

        self.status_label = Gtk.Label(label="Status: Stopped", xalign=0)
        outer.append(self.status_label)

        GLib.timeout_add(1000, self._update_status)

    def _collect_config(self):
        return {
            "base_step": int(self.base_spin.get_value()),
            "max_step": int(self.max_spin.get_value()),
            "window_ms": int(self.window_spin.get_value()),
            "hold_accel": self.hold_check.get_active(),
            "brightness_acceleration": self.brightness_accel_check.get_active(),
            "sound_acceleration": self.sound_accel_check.get_active(),
        }

    def _on_save(self, _btn):
        self._stop_daemon()
        config = self._collect_config()
        save_config(config)
        self._update_autostart_status()
        self._start_daemon()
        self.status_label.set_text("Status: Running")

    def _update_autostart_status(self):
        if AUTOSTART_FILE.exists():
            self.autostart_status.set_text("Startup: enabled")
        else:
            self.autostart_status.set_text("Startup: disabled")

    def _on_add_autostart(self, _btn):
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Fn Keys Accel\n"
            f"Exec={sys.executable} {Path(__file__).resolve()} --daemon\n"
            "Hidden=false\n"
            "NoDisplay=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        self._update_autostart_status()

    def _on_remove_autostart(self, _btn):
        AUTOSTART_FILE.unlink(missing_ok=True)
        self._update_autostart_status()

    def _start_daemon(self):
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _stop_daemon(self):
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
                os.kill(pid, signal.SIGTERM)
            except (ValueError, ProcessLookupError):
                pass
            for _ in range(20):
                if not LOCK_FILE.exists():
                    break
                time.sleep(0.1)
            LOCK_FILE.unlink(missing_ok=True)
        self._update_status()

    def _update_status(self):
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
                os.kill(pid, 0)
                self.status_label.set_text("Status: Running")
            except (ValueError, ProcessLookupError):
                LOCK_FILE.unlink(missing_ok=True)
                self.status_label.set_text("Status: Stopped")
        else:
            self.status_label.set_text("Status: Stopped")
        return True

    def _on_stop(self, _btn):
        self._stop_daemon()

    def _on_quit(self, _btn):
        self.get_application().quit()


class BrightnessApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.github.fn_keys_accel")

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = AppWindow(self)
            win.present()


def main():
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        app = BrightnessApp()
        sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
