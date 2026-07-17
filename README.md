# Window Region Share

Occlusion-proof window (or cropped region) mirroring for online meetings — a Python take on [Region to Share](https://github.com/tom-englert/RegionToShare), with one important difference:

**Region to Share** mirrors screen pixels in a framed area (whatever is on top wins).  
**This app** captures a **specific window** via Windows Graphics Capture, so the mirrored content stays correct even when other apps cover that window.

## How to use

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run:

```bash
python main.py
```

3. Select a target — either a **[Display N]** (whole monitor) or a **window** (or **Click to pick…** / `Ctrl+Shift+R`).
4. Optionally **Set crop…** to share only part of that target.
5. Click **Start Sharing**.
6. In Teams / Zoom / Google Meet, share the window named **Special Region to Share**.

### Displays vs windows

- **[Display N]** entries capture an entire monitor. On multi-monitor setups with
  different scaling (e.g. 150% + 100%), the crop is mapped in physical pixels so it
  stays aligned.
- **Window** entries capture just that window and stay correct even when covered by
  other apps.

### Presentation mode (share only the region)

- **On by default.** The mirror window's own title bar is removed so the shared image
  contains *only* the captured region — no "Special Region to Share" caption or window
  buttons, and no taskbar strip.
- The mirror still shows up in the meeting app's window picker and taskbar.
- The window auto-sizes to the region's aspect ratio (no black bars).
- With no title bar and no on-screen controls (so nothing extra is ever captured):
  **left-drag** the region to move the window, **right-drag** to resize it.
  Uncheck **Presentation mode** to get the normal title bar back.

### Selection confirmation & cursor

- Selecting a target flashes a **red boundary** around that window/display so you can
  confirm the right one. It auto-hides and is never included in the shared image.
- **Show mouse cursor** is on by default, so the pointer appears in the shared region
  with its current shape (e.g. the text I-beam when hovering an editable field). The
  blinking text caret is part of the app's own content and is always captured.

### System tray

- The app lives in the **system tray**. Closing the control panel (X) **minimizes to
  the tray** instead of quitting.
- **Right-click the tray icon** for: Show/Hide control panel, Show mirror window,
  Start/Stop sharing, Pause/Resume, Pick window, and Quit.
- **Double-click** (or left-click) the tray icon to bring back the control panel.
- Use **Quit** in the tray menu to fully exit.

## Hotkeys

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+P` | Pause / resume |
| `Ctrl+Shift+R` | Click-to-pick target window |

## Performance

The pipeline is tuned for low overhead:

- One array copy per kept frame (BGRA→RGB via OpenCV), and frames are only produced
  when the window content actually changes (Windows Graphics Capture is event-driven).
- Fast OpenCV resizing with a cached window size (no per-frame layout passes).
- Frame pacing is handled once (no double-throttling / jitter).

Two knobs in **Settings** if you need to trade quality for speed:

- **Target FPS** (default 20) — lower it (e.g. 12-15) on slower machines.
- **Quality** (default Balanced/1440p) — caps the largest output dimension:
  Performance (1080p), Balanced (1440p), High (2160p), or Full (no cap). Lower = faster
  and lighter, especially when capturing large or high-DPI windows/monitors.

Both can be changed live while sharing.

## Capture backends

1. **WGC** — `windows-capture` (Windows Graphics Capture) for both windows and monitors. Works while a window target is occluded.
2. **PrintWindow** — fallback for windows using `PW_RENDERFULLCONTENT` if WGC cannot start.
3. **BitBlt** — fallback for monitor targets (full-screen copy) if WGC cannot start.

Some protected / exclusive-fullscreen surfaces may still capture blank; use borderless windowed mode when possible.

## Smoke test

```bash
python smoke_test.py --seconds 2 --save frame.png
```

## Build a standalone Windows app (.exe)

You can package everything into a single windowed executable (no Python needed to run it).

1. Install the build tool:

```bash
pip install pyinstaller
```

2. (Optional) regenerate the icon:

```bash
python build_icon.py
```

3. Build:

```bash
pyinstaller --noconfirm --clean SpecialRegionToShare.spec
```

The result is `dist/SpecialRegionToShare.exe` (a single ~70 MB file). Double-click it to
run — it starts in the system tray with the control panel open.

Notes:
- It's a **one-file** build, so first launch is a little slower (it unpacks to a temp dir).
- The native `windows-capture` module, OpenCV, `pystray`, and `pynput` are bundled
  automatically via the spec's `collect_all`.
- Some antivirus tools flag unsigned PyInstaller one-file exes; code-signing avoids this.

## Requirements

- Windows 10 / 11
- Python 3.9+ (only to run from source or to build the exe)
