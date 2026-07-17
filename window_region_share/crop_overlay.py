"""Fullscreen overlay to pick a crop rectangle over the target window."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from .capture import CropRect
from .windows import get_client_screen_rect, get_client_size


class CropOverlay:
    """Semi-transparent overlay for dragging a crop region.

    `screen_rect` is the (left, top, right, bottom) physical-pixel area the
    overlay covers. `frame_size` is the (width, height) of the captured frame
    that the crop coordinates map into.
    """

    def __init__(
        self,
        master: tk.Misc,
        on_done: Callable[[Optional[CropRect]], None],
        *,
        screen_rect: tuple[int, int, int, int],
        frame_size: tuple[int, int],
    ) -> None:
        self.master = master
        self.on_done = on_done
        self._start: Optional[tuple[int, int]] = None
        self._rect_id: Optional[int] = None

        sx, sy, ex, ey = screen_rect
        self._client_w, self._client_h = frame_size
        self._screen_x = sx
        self._screen_y = sy

        self.win = tk.Toplevel(master)
        self.win.title("Draw crop region — release to apply, Esc cancel, R full")
        self.win.geometry(f"{max(1, ex - sx)}x{max(1, ey - sy)}+{sx}+{sy}")
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.35)
        self.win.configure(bg="#000000")
        self.win.overrideredirect(True)

        self.canvas = tk.Canvas(
            self.win, bg="#1a1a2e", highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            12,
            12,
            anchor="nw",
            fill="#ffffff",
            font=("Segoe UI", 11),
            text="Drag a box, then release to apply · Esc = cancel · R = full window",
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.win.bind("<Return>", lambda e: self._confirm())
        self.win.bind("<Escape>", lambda e: self._cancel())
        self.win.bind("r", lambda e: self._reset_full())
        self.win.bind("R", lambda e: self._reset_full())
        self.win.focus_force()

        self._crop: Optional[CropRect] = None

    @classmethod
    def for_window(
        cls,
        master: tk.Misc,
        hwnd: int,
        on_done: Callable[[Optional[CropRect]], None],
    ) -> "CropOverlay":
        return cls(
            master,
            on_done,
            screen_rect=get_client_screen_rect(hwnd),
            frame_size=get_client_size(hwnd),
        )

    @classmethod
    def for_monitor(
        cls,
        master: tk.Misc,
        rect: tuple[int, int, int, int],
        on_done: Callable[[Optional[CropRect]], None],
    ) -> "CropOverlay":
        left, top, right, bottom = rect
        return cls(
            master,
            on_done,
            screen_rect=rect,
            frame_size=(right - left, bottom - top),
        )

    def _on_press(self, event: tk.Event) -> None:
        self._start = (event.x, event.y)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event: tk.Event) -> None:
        if not self._start:
            return
        x0, y0 = self._start
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            x0, y0, event.x, event.y, outline="#00e5ff", width=2, fill="#00e5ff"
        )
        self.canvas.itemconfigure(self._rect_id, stipple="gray50")

    def _on_release(self, event: tk.Event) -> None:
        if not self._start:
            return
        x0, y0 = self._start
        x1, y1 = event.x, event.y
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        drag_w = right - left
        drag_h = bottom - top
        # Ignore accidental clicks / tiny drags
        if drag_w < 8 or drag_h < 8:
            self._start = None
            return
        # Map overlay coords → client pixel coords
        ow = max(1, self.win.winfo_width())
        oh = max(1, self.win.winfo_height())
        scale_x = self._client_w / ow
        scale_y = self._client_h / oh
        cx = int(left * scale_x)
        cy = int(top * scale_y)
        cw = max(1, int(drag_w * scale_x))
        ch = max(1, int(drag_h * scale_y))
        self._crop = CropRect(cx, cy, cw, ch)
        # Commit immediately on release so the user doesn't have to press Enter.
        self._confirm()

    def _confirm(self) -> None:
        if self._crop is None:
            # No drag — treat as full window
            crop: Optional[CropRect] = None
        else:
            crop = self._crop
        self._close()
        self.on_done(crop)

    def _reset_full(self) -> None:
        self._close()
        self.on_done(None)

    def _cancel(self) -> None:
        # Discard overlay without changing existing crop (signal via Ellipsis)
        self._close()
        self.on_done(Ellipsis)  # type: ignore[arg-type]

    def _close(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass
