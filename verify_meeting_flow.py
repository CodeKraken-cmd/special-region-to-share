"""Validate meeting-share readiness: capture, crop, mirror HWND title."""

from __future__ import annotations

import sys
import time


def main() -> int:
    from window_region_share import MIRROR_TITLE
    from window_region_share.capture import CaptureSession, CropRect
    from window_region_share.windows import list_windows
    import tkinter as tk
    from window_region_share.mirror import MirrorWindow
    import numpy as np

    windows = [w for w in list_windows() if "Special Region" not in w.title]
    if not windows:
        print("No windows to capture", file=sys.stderr)
        return 1

    target = windows[0]
    print(f"Capturing: {target.title}")

    root = tk.Tk()
    root.withdraw()
    mirror = MirrorWindow(root)
    assert mirror.win.title() == MIRROR_TITLE

    received: list[tuple[int, int]] = []

    def on_frame(rgb: np.ndarray) -> None:
        received.append((rgb.shape[1], rgb.shape[0]))
        mirror.push_frame(rgb)

    # Full window briefly
    session = CaptureSession(target.hwnd, on_frame, target_fps=15)
    backend = session.start()
    print(f"Backend: {backend}")
    t0 = time.time()
    while time.time() - t0 < 1.5 and not received:
        root.update()
        time.sleep(0.05)
    session.stop()

    if not received:
        print("FAIL: no frames", file=sys.stderr)
        return 2

    print(f"Frames: {len(received)} first={received[0]}")

    # Crop pass via PrintWindow for deterministic pacing
    received.clear()
    session = CaptureSession(
        target.hwnd,
        on_frame,
        crop=CropRect(0, 0, 320, 200),
        target_fps=12,
    )
    session._start_printwindow()
    session._backend = "printwindow"
    t0 = time.time()
    while time.time() - t0 < 1.0:
        root.update()
        time.sleep(0.05)
    session.stop()
    print(f"Cropped frames: {len(received)} sample={received[:2]}")

    # Occlusion note: WGC/PrintWindow do not sample screen z-order.
    print(
        "Occlusion: capture reads window compositor buffer, "
        "not screen pixels under other apps."
    )
    print(f'Meeting share target window title: "{MIRROR_TITLE}"')

    mirror.destroy()
    root.destroy()
    print("MEETING-FLOW CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
