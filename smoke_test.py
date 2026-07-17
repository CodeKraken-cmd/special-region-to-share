#!/usr/bin/env python3
"""Smoke-test capture backends without the full UI."""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture smoke test")
    parser.add_argument(
        "--seconds", type=float, default=2.0, help="How long to capture"
    )
    parser.add_argument(
        "--hwnd", type=int, default=0, help="HWND to capture (0 = first listed)"
    )
    parser.add_argument("--save", type=str, default="", help="Optional PNG path")
    args = parser.parse_args()

    from window_region_share.windows import list_windows
    from window_region_share.capture import CaptureSession

    windows = list_windows()
    if not windows:
        print("No capturable windows found", file=sys.stderr)
        return 1

    target = None
    if args.hwnd:
        target = next((w for w in windows if w.hwnd == args.hwnd), None)
        if target is None:
            # Still try raw hwnd
            from window_region_share.windows import WindowInfo
            import win32gui

            target = WindowInfo(
                hwnd=args.hwnd,
                title=win32gui.GetWindowText(args.hwnd) or str(args.hwnd),
                class_name="",
                pid=0,
            )
    else:
        target = windows[0]

    print(f"Target: {target.title} (hwnd={target.hwnd})")
    frames: list[np.ndarray] = []

    def on_frame(rgb: np.ndarray) -> None:
        frames.append(rgb)
        print(f"  frame {len(frames)}: {rgb.shape[1]}x{rgb.shape[0]}")

    session = CaptureSession(target.hwnd, on_frame, target_fps=10, capture_cursor=False)
    backend = session.start()
    print(f"Backend: {backend}")
    time.sleep(args.seconds)
    session.stop()
    print(f"Captured {len(frames)} frames")

    if not frames:
        print("FAIL: no frames received", file=sys.stderr)
        return 2

    if args.save:
        from PIL import Image

        Image.fromarray(frames[-1], mode="RGB").save(args.save)
        print(f"Saved {args.save}")

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
