"""Shareable mirror window that meeting apps can select."""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk

from . import MIRROR_TITLE

_PLACEHOLDER = (
    "Select a target and press Start Sharing.\n\n"
    "In Teams / Zoom / Meet, share this window:\n"
    f'"{MIRROR_TITLE}"'
)

_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080


class MirrorWindow:
    """Top-level window that displays mirrored capture frames.

    In presentation (frameless) mode the OS title bar is removed so the shared
    image contains only the captured region — no "Special Region to Share"
    caption or window buttons.
    """

    def __init__(self, master: tk.Misc) -> None:
        self.win = tk.Toplevel(master)
        self.win.title(MIRROR_TITLE)
        self.win.geometry("960x540")
        self.win.minsize(240, 135)
        self.win.configure(bg="#000000")
        self.win.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self._label = tk.Label(
            self.win,
            text=_PLACEHOLDER,
            fg="#dddddd",
            bg="#000000",
            font=("Segoe UI", 12),
            justify="center",
        )
        self._label.pack(fill="both", expand=True)

        # Frameless move/resize with no visible chrome (nothing to capture):
        #   left-drag  = move the window
        #   right-drag = resize the window
        self._drag_offset: Optional[tuple[int, int]] = None
        self._label.bind("<ButtonPress-1>", self._start_move)
        self._label.bind("<B1-Motion>", self._on_move)
        self._label.bind("<ButtonPress-3>", self._start_resize)
        self._label.bind("<B3-Motion>", self._on_resize)

        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=2)
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._always_on_top = False
        self._frameless = False
        self._closed = False
        self._poll_id: Optional[str] = None
        self._resize_start: Optional[tuple[int, int, int, int]] = None
        self._fit_pending = False
        # Cached display size (updated on <Configure>, not per frame)
        self._disp_w = 960
        self._disp_h = 540
        self.win.bind("<Configure>", self._on_configure)
        self._start_poll()

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self.win:
            self._disp_w = max(1, event.width)
            self._disp_h = max(1, event.height)

    def request_fit(self) -> None:
        """Size the window to the next frame's aspect ratio (no black bars)."""
        self._fit_pending = True

    def _fit_window_to(self, w: int, h: int) -> None:
        max_dim = 1280
        scale = min(1.0, max_dim / max(w, h))
        tw = max(240, int(w * scale))
        th = max(135, int(h * scale))
        self.win.geometry(f"{tw}x{th}")

    def _on_close_request(self) -> None:
        self.win.withdraw()

    def show(self) -> None:
        self.win.deiconify()
        self.win.lift()

    def set_always_on_top(self, enabled: bool) -> None:
        self._always_on_top = enabled
        self.win.attributes("-topmost", enabled)

    def set_frameless(self, enabled: bool) -> None:
        """Toggle borderless presentation mode (no title bar in the share)."""
        if enabled == self._frameless:
            return
        self._frameless = enabled
        self.win.overrideredirect(enabled)
        # Re-assert taskbar / share-picker visibility after style change
        self.win.after(10, self._apply_appwindow)
        # Remap so the change takes effect and the window stays visible
        self.win.after(20, self._remap)

    def _remap(self) -> None:
        if self._closed:
            return
        try:
            was_topmost = self._always_on_top
            self.win.withdraw()
            self.win.deiconify()
            self.win.lift()
            if was_topmost:
                self.win.attributes("-topmost", True)
        except Exception:
            pass

    def _apply_appwindow(self) -> None:
        try:
            hwnd = self.win.winfo_id()
            parent = ctypes.windll.user32.GetParent(hwnd)
            target = parent if parent else hwnd
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(target, _GWL_EXSTYLE)
            style = (style & ~_WS_EX_TOOLWINDOW) | _WS_EX_APPWINDOW
            user32.SetWindowLongW(target, _GWL_EXSTYLE, style)
        except Exception:
            pass

    def _start_move(self, event: tk.Event) -> None:
        if not self._frameless:
            return
        self._drag_offset = (event.x_root - self.win.winfo_x(), event.y_root - self.win.winfo_y())

    def _on_move(self, event: tk.Event) -> None:
        if not self._frameless or self._drag_offset is None:
            return
        dx, dy = self._drag_offset
        self.win.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _start_resize(self, event: tk.Event) -> None:
        if not self._frameless:
            return
        self._resize_start = (
            event.x_root,
            event.y_root,
            self.win.winfo_width(),
            self.win.winfo_height(),
        )

    def _on_resize(self, event: tk.Event) -> None:
        if self._resize_start is None:
            return
        sx, sy, sw, sh = self._resize_start
        new_w = max(240, sw + (event.x_root - sx))
        new_h = max(135, sh + (event.y_root - sy))
        self.win.geometry(f"{new_w}x{new_h}")

    def push_frame(self, rgb: np.ndarray) -> None:
        if self._closed:
            return
        try:
            self._frame_queue.put_nowait(rgb)
        except queue.Full:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(rgb)
            except queue.Full:
                pass

    def clear(self) -> None:
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        self._label.configure(image="", text=_PLACEHOLDER)
        self._photo = None

    def _start_poll(self) -> None:
        self._poll()

    def _poll(self) -> None:
        if self._closed:
            return
        latest: Optional[np.ndarray] = None
        while True:
            try:
                latest = self._frame_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._show_frame(latest)
        self._poll_id = self.win.after(16, self._poll)

    def _show_frame(self, rgb: np.ndarray) -> None:
        h, w = rgb.shape[:2]
        if self._fit_pending:
            self._fit_pending = False
            self._fit_window_to(w, h)
            self._disp_w, self._disp_h = self.win.winfo_width(), self.win.winfo_height()

        # Use cached window size (no per-frame update_idletasks).
        cw = max(1, self._disp_w)
        ch = max(1, self._disp_h)
        scale = min(cw / w, ch / h)
        tw = max(1, int(w * scale))
        th = max(1, int(h * scale))

        if (tw, th) != (w, h):
            # cv2.resize is markedly faster than PIL for large frames.
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            resized = cv2.resize(rgb, (tw, th), interpolation=interp)
        else:
            resized = rgb

        self._photo = ImageTk.PhotoImage(Image.fromarray(resized, mode="RGB"))
        self._label.configure(image=self._photo, text="")

    def destroy(self) -> None:
        self._closed = True
        if self._poll_id is not None:
            try:
                self.win.after_cancel(self._poll_id)
            except Exception:
                pass
        try:
            self.win.destroy()
        except Exception:
            pass
