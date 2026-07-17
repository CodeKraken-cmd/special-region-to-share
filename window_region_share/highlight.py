"""Click-through red boundary overlay to confirm the selected target."""

from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Optional

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_TRANSPARENT_KEY = "#010101"


class BoundaryHighlight:
    """Draws a red rectangle border around a screen rect without stealing focus.

    The center is transparent and the window is click-through, so it never
    interferes with the target app. Auto-hides after a short delay.
    """

    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self.win: Optional[tk.Toplevel] = None
        self._hide_after: Optional[str] = None

    def show(
        self,
        rect: tuple[int, int, int, int],
        *,
        color: str = "#ff2d2d",
        thickness: int = 5,
        auto_hide_ms: Optional[int] = 1600,
    ) -> None:
        self.hide()
        left, top, right, bottom = rect
        w = max(1, right - left)
        h = max(1, bottom - top)

        win = tk.Toplevel(self.master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{w}x{h}+{left}+{top}")
        win.configure(bg=_TRANSPARENT_KEY)
        try:
            win.attributes("-transparentcolor", _TRANSPARENT_KEY)
        except tk.TclError:
            pass

        canvas = tk.Canvas(
            win, bg=_TRANSPARENT_KEY, highlightthickness=0, bd=0
        )
        canvas.pack(fill="both", expand=True)
        half = thickness / 2
        canvas.create_rectangle(
            half, half, w - half, h - half, outline=color, width=thickness
        )

        win.update_idletasks()
        self.win = win
        self._make_click_through()

        if auto_hide_ms is not None:
            self._hide_after = self.master.after(auto_hide_ms, self.hide)

    def _make_click_through(self) -> None:
        if self.win is None:
            return
        try:
            hwnd = self.win.winfo_id()
            user32 = ctypes.windll.user32
            styles = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                _GWL_EXSTYLE,
                styles
                | _WS_EX_LAYERED
                | _WS_EX_TRANSPARENT
                | _WS_EX_TOOLWINDOW,
            )
        except Exception:
            pass

    def hide(self) -> None:
        if self._hide_after is not None:
            try:
                self.master.after_cancel(self._hide_after)
            except Exception:
                pass
            self._hide_after = None
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None
