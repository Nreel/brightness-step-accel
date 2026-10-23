# Brightness Step Accelerator

A small GTK4 application for Linux that makes the brightness step grow when the
brightness keys are tapped rapidly — similar to the Windows behaviour where
faster clicking gives a bigger step.

It listens directly to the raw `evdev` input layer, so it works on X11 and
Wayland and does not depend on KDE, GNOME, or any desktop shortcut system.

## Features

- Configurable **base step** (single tap), **max step** (rapid tap), and
  **rapid-tap window**.
- GUI to change settings without editing scripts.
- Toggle **enable on startup** (creates a standard autostart entry).
- Start / stop the background daemon from the GUI.
- Single daemon instance guarded by a lock file.
- Standalone **AppImage** and **single-file binary** releases.

## Requirements

- Python 3 with `python-evdev` and `python-gobject` (GTK4 bindings).
- `brightnessctl` **or** write access to `/sys/class/backlight/*/brightness`.
- Membership in the `input` group for raw keyboard access.

### CachyOS / Arch

```bash
sudo pacman -S python-evdev python-gobject brightnessctl
sudo usermod -aG input "$USER"
# Log out and back in so the group change takes effect.
```

### Debian / Ubuntu

```bash
sudo apt install python3-evdev python3-gi gir1.2-gtk-4.0 brightnessctl
sudo usermod -aG input "$USER"
# Log out and back in so the group change takes effect.
```

## Installation

### AppImage (recommended for most users)

Download the latest `brightness-step-accel.AppImage` from the
[Releases](https://github.com/nreel/brightness-step-accel/releases) page.

```bash
chmod +x brightness-step-accel.AppImage
./brightness-step-accel.AppImage
```

### Single-file binary

Download `brightness-step-accel` from the Releases page.

```bash
chmod +x brightness-step-accel
./brightness-step-accel
```

### From source

```bash
git clone https://github.com/nreel/brightness-step-accel.git
cd brightness-step-accel
python3 app.py            # open the GUI
```

## Usage

```bash
python3 app.py            # open the GUI
python3 app.py --daemon   # run the daemon directly
```

In the GUI:

1. Adjust **Base step**, **Max step**, and **Rapid tap window**.
2. Tick **Enable on startup** if you want the daemon to run at login.
3. Click **Save & Restart**.
4. Use **Stop** to stop the daemon. **Quit** closes the GUI and leaves the
   daemon running (if started).

### Configuration file

Settings are stored in `~/.config/brightness-step-accel/config.json`:

```json
{
  "base_step": 2,
  "max_step": 20,
  "window_ms": 200
}
```

- `base_step`: percentage change for a single tap.
- `max_step`: maximum percentage change when tapping rapidly.
- `window_ms`: time window in milliseconds for counting rapid taps.

## Building

The build script creates both a standalone binary and an AppImage:

```bash
./build.sh
```

Artifacts are written to `dist/`:

- `dist/brightness-step-accel` — standalone binary.
- `dist/brightness-step-accel.AppImage` — portable AppImage.

The script creates a virtual environment with `--system-site-packages` so
PyInstaller can find the system `gi` (GTK) bindings. It also downloads
`appimagetool` into `build_tools/` if it is not present.

### Automated releases

Pushing a tag matching `v*` triggers the GitHub Actions workflow in
`.github/workflows/release.yml`, which builds the binary and AppImage on an
Ubuntu runner and attaches both to a GitHub Release.

```bash
git tag v1.0.0
git push origin v1.0.0
```

## How it works

The daemon grabs keyboards that expose brightness keys, swallows those key
events, and forwards everything else to a virtual `uinput` device so the
keyboard keeps working normally. For each press it measures the time since the
last press of the same key. If the gap is within the configured window, the
step grows; otherwise it resets to the base step. The resulting percentage is
sent to `brightnessctl`, with a direct sysfs fallback.

## Notes

- Grabbing the device means the desktop's own brightness handler does not see
  those keys. That is intentional — the app takes full control.
- If no backlight device is writable, install `brightnessctl` or run the daemon
  with appropriate privileges.
- The autostart entry uses the absolute path of `app.py`, so keep the file in a
  stable location if you rely on startup.
- The AppImage and binary are built for x86_64.
