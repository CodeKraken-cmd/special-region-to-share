"""Enumerate and inspect top-level windows."""

from __future__ import annotations

from dataclasses import dataclass

import win32api
import win32gui
import win32con
import win32process


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int

    @property
    def display_name(self) -> str:
        title = self.title.strip() or "(untitled)"
        return f"{title}  [hwnd={self.hwnd}]"


@dataclass(frozen=True)
class MonitorInfo:
    """A physical display. `wgc_index` is 1-based for windows-capture."""

    wgc_index: int
    device: str
    left: int
    top: int
    right: int
    bottom: int
    primary: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def display_name(self) -> str:
        tag = " (primary)" if self.primary else ""
        return f"[Display {self.wgc_index}] {self.width}x{self.height}{tag}"


def list_monitors() -> list[MonitorInfo]:
    """List physical monitors with physical-pixel rects (requires DPI awareness).

    Order matches windows-capture's 1-based `monitor_index`.
    """
    monitors: list[MonitorInfo] = []
    handles = win32api.EnumDisplayMonitors()
    for i, (h_mon, _hdc, _rect) in enumerate(handles):
        try:
            info = win32api.GetMonitorInfo(h_mon)
        except Exception:
            continue
        left, top, right, bottom = info["Monitor"]
        monitors.append(
            MonitorInfo(
                wgc_index=i + 1,
                device=str(info.get("Device", f"DISPLAY{i + 1}")),
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                primary=bool(info.get("Flags", 0) & 1),
            )
        )
    return monitors


def _is_capturable(hwnd: int) -> bool:
    if not win32gui.IsWindow(hwnd):
        return False
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
        return False
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    if style & win32con.WS_DISABLED:
        return False
    title = win32gui.GetWindowText(hwnd)
    # Skip tool windows with empty titles (shell chrome, etc.)
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if (ex_style & win32con.WS_EX_TOOLWINDOW) and not title:
        return False
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if (right - left) < 32 or (bottom - top) < 32:
        return False
    return True


def list_windows(*, exclude_hwnds: set[int] | None = None) -> list[WindowInfo]:
    exclude = exclude_hwnds or set()
    results: list[WindowInfo] = []

    def callback(hwnd: int, _: object) -> bool:
        if hwnd in exclude:
            return True
        if not _is_capturable(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return True
        if title == MIRROR_TITLE_SAFE or title.startswith("Special Region to Share"):
            return True
        try:
            class_name = win32gui.GetClassName(hwnd)
        except Exception:
            class_name = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0
        results.append(WindowInfo(hwnd=hwnd, title=title, class_name=class_name, pid=pid))
        return True

    win32gui.EnumWindows(callback, None)
    results.sort(key=lambda w: w.title.lower())
    return results


# Avoid circular import of package constant during early import
MIRROR_TITLE_SAFE = "Special Region to Share"


def get_client_size(hwnd: int) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return max(1, right - left), max(1, bottom - top)


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    return win32gui.GetWindowRect(hwnd)


def get_client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    point_left_top = win32gui.ClientToScreen(hwnd, (left, top))
    point_right_bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
    return (
        point_left_top[0],
        point_left_top[1],
        point_right_bottom[0],
        point_right_bottom[1],
    )


def window_from_point(x: int, y: int) -> int:
    return int(win32gui.WindowFromPoint((x, y)))


def get_root_window(hwnd: int) -> int:
    root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
    return int(root or hwnd)


def is_window_alive(hwnd: int) -> bool:
    return bool(win32gui.IsWindow(hwnd))
