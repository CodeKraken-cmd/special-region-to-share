"""Window capture: Windows Graphics Capture primary, PrintWindow fallback."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

FrameCallback = Callable[[np.ndarray], None]


@dataclass
class CropRect:
    """Crop in captured-frame pixel coordinates (inclusive-exclusive)."""

    x: int
    y: int
    width: int
    height: int

    def clamp(self, frame_w: int, frame_h: int) -> "CropRect":
        x = max(0, min(self.x, max(0, frame_w - 1)))
        y = max(0, min(self.y, max(0, frame_h - 1)))
        w = max(1, min(self.width, frame_w - x))
        h = max(1, min(self.height, frame_h - y))
        return CropRect(x, y, w, h)

    def apply(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        c = self.clamp(w, h)
        return frame[c.y : c.y + c.height, c.x : c.x + c.width].copy()


class CaptureSession:
    """Owns an active capture of a single HWND and emits RGB frames."""

    def __init__(
        self,
        hwnd: Optional[int],
        on_frame: FrameCallback,
        *,
        monitor_index: Optional[int] = None,
        monitor_rect: Optional[tuple[int, int, int, int]] = None,
        crop: Optional[CropRect] = None,
        target_fps: int = 20,
        capture_cursor: bool = False,
        draw_border: bool = False,
        max_output_dim: Optional[int] = 1440,
    ) -> None:
        self.hwnd = hwnd
        self.monitor_index = monitor_index
        self.monitor_rect = monitor_rect
        self.on_frame = on_frame
        self.crop = crop
        # Cap the largest output dimension to keep the pipeline light.
        self.max_output_dim = max_output_dim
        self.target_fps = max(1, min(60, target_fps))
        self.capture_cursor = capture_cursor
        self.draw_border = draw_border

        self._paused = False
        self._lock = threading.Lock()
        self._backend = "none"
        self._wgc_control = None
        self._print_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._min_interval = 1.0 / self.target_fps

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def set_crop(self, crop: Optional[CropRect]) -> None:
        with self._lock:
            self.crop = crop

    def set_target_fps(self, fps: int) -> None:
        self.target_fps = max(1, min(60, fps))
        self._min_interval = 1.0 / self.target_fps

    @property
    def is_monitor(self) -> bool:
        return self.monitor_index is not None

    def start(self) -> str:
        """Start capture. Returns backend name used."""
        if self._try_start_wgc():
            self._backend = "wgc"
            return self._backend
        if self.is_monitor:
            logger.warning("WGC failed; falling back to screen BitBlt")
            self._start_screen_grab()
            self._backend = "bitblt"
            return self._backend
        logger.warning("WGC failed; falling back to PrintWindow")
        self._start_printwindow()
        self._backend = "printwindow"
        return self._backend

    def stop(self) -> None:
        self._stop_event.set()
        if self._wgc_control is not None:
            try:
                self._wgc_control.stop()
            except Exception:
                logger.exception("Error stopping WGC")
            self._wgc_control = None
        if self._print_thread is not None:
            self._print_thread.join(timeout=2.0)
            self._print_thread = None

    def _emit_bgra(self, bgra: np.ndarray) -> None:
        # Frame pacing is handled upstream (WGC minimum_update_interval, or the
        # fallback loops' sleep), so no extra throttle here — that only added
        # jitter by dropping slightly-early frames.
        if self._paused or self._stop_event.is_set():
            return
        if bgra is None or bgra.size == 0:
            return
        h, w = bgra.shape[:2]
        with self._lock:
            crop = self.crop
        if crop is not None:
            c = crop.clamp(w, h)
            region = bgra[c.y : c.y + c.height, c.x : c.x + c.width]
        else:
            region = bgra

        rh, rw = region.shape[:2]
        cap = self.max_output_dim
        if cap and max(rw, rh) > cap:
            scale = cap / max(rw, rh)
            ow = max(1, int(rw * scale))
            oh = max(1, int(rh * scale))
            # Downscale on BGRA (fast, SIMD), then convert the smaller image.
            small = cv2.resize(region, (ow, oh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGRA2RGB)
        else:
            # BGRA -> RGB in a single contiguous copy (the only copy per frame).
            rgb = cv2.cvtColor(region, cv2.COLOR_BGRA2RGB)
        try:
            self.on_frame(rgb)
        except Exception:
            logger.exception("Frame callback failed")

    def _try_start_wgc(self) -> bool:
        try:
            from windows_capture import WindowsCapture
        except ImportError:
            logger.error("windows-capture not installed")
            return False

        try:
            interval_ms = int(1000 / self.target_fps)
            if self.is_monitor:
                capture = WindowsCapture(
                    cursor_capture=self.capture_cursor,
                    draw_border=self.draw_border,
                    minimum_update_interval=interval_ms,
                    monitor_index=int(self.monitor_index),
                )
            else:
                capture = WindowsCapture(
                    cursor_capture=self.capture_cursor,
                    draw_border=self.draw_border,
                    minimum_update_interval=interval_ms,
                    window_hwnd=int(self.hwnd),
                )

            session = self

            @capture.event
            def on_frame_arrived(frame, capture_control):
                if session._stop_event.is_set():
                    capture_control.stop()
                    return
                # Process synchronously: the buffer is valid for this call, and
                # _emit_bgra makes exactly one copy (only for frames we keep).
                session._emit_bgra(frame.frame_buffer)

            @capture.event
            def on_closed():
                logger.info("WGC session closed (target window gone?)")

            self._wgc_control = capture.start_free_threaded()
            return True
        except Exception:
            logger.exception("Failed to start Windows Graphics Capture")
            return False

    def _start_printwindow(self) -> None:
        self._stop_event.clear()
        self._print_thread = threading.Thread(
            target=self._printwindow_loop,
            name="PrintWindowCapture",
            daemon=True,
        )
        self._print_thread.start()

    def _printwindow_loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        import win32gui
        import win32ui

        user32 = ctypes.windll.user32
        PW_RENDERFULLCONTENT = 0x00000002
        PW_CLIENTONLY = 0x00000001

        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(0.05)
                continue
            if not win32gui.IsWindow(self.hwnd):
                break
            try:
                left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
                width = right - left
                height = bottom - top
                if width < 1 or height < 1:
                    time.sleep(0.05)
                    continue

                hwnd_dc = win32gui.GetWindowDC(self.hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
                save_dc.SelectObject(bitmap)

                ok = user32.PrintWindow(
                    self.hwnd,
                    save_dc.GetSafeHdc(),
                    PW_CLIENTONLY | PW_RENDERFULLCONTENT,
                )
                if not ok:
                    ok = user32.PrintWindow(
                        self.hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
                    )

                bmpinfo = bitmap.GetInfo()
                bmpstr = bitmap.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8)
                img = img.reshape((bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4))

                win32gui.DeleteObject(bitmap.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)

                if ok:
                    self._emit_bgra(img)
            except Exception:
                logger.exception("PrintWindow capture error")
                time.sleep(0.1)
                continue

            # Pace the loop roughly to target FPS
            time.sleep(self._min_interval)

    def _start_screen_grab(self) -> None:
        self._stop_event.clear()
        self._print_thread = threading.Thread(
            target=self._screen_grab_loop,
            name="ScreenGrabCapture",
            daemon=True,
        )
        self._print_thread.start()

    def _screen_grab_loop(self) -> None:
        import win32gui
        import win32ui

        if self.monitor_rect is None:
            logger.error("Monitor rect required for screen grab fallback")
            return
        left, top, right, bottom = self.monitor_rect
        width = right - left
        height = bottom - top

        while not self._stop_event.is_set():
            if self._paused:
                time.sleep(0.05)
                continue
            try:
                desktop_dc = win32gui.GetDC(0)
                mfc_dc = win32ui.CreateDCFromHandle(desktop_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
                save_dc.SelectObject(bitmap)
                save_dc.BitBlt(
                    (0, 0), (width, height), mfc_dc, (left, top), 0x00CC0020  # SRCCOPY
                )
                bmpstr = bitmap.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                    (height, width, 4)
                )
                win32gui.DeleteObject(bitmap.GetHandle())
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(0, desktop_dc)
                self._emit_bgra(img)
            except Exception:
                logger.exception("Screen grab error")
                time.sleep(0.1)
                continue
            time.sleep(self._min_interval)
