"""Control panel and app orchestration."""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

import win32api
import win32con
import win32gui

from . import APP_NAME, MIRROR_TITLE
from .capture import CaptureSession, CropRect
from .crop_overlay import CropOverlay
from .highlight import BoundaryHighlight
from .hotkeys import HotkeyManager
from .mirror import MirrorWindow
from .tray import SystemTray
from .windows import (
    MonitorInfo,
    WindowInfo,
    get_root_window,
    get_window_rect,
    is_window_alive,
    list_monitors,
    list_windows,
    window_from_point,
)

logger = logging.getLogger(__name__)


def enable_dpi_awareness() -> None:
    try:
        ctypes_ok = False
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            ctypes_ok = True
        except Exception:
            pass
        if not ctypes_ok:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        logger.debug("DPI awareness not set", exc_info=True)


class App:
    def __init__(self) -> None:
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} — Control")
        self.root.geometry("520x720")
        self.root.minsize(480, 560)

        self.mirror = MirrorWindow(self.root)
        self.highlighter = BoundaryHighlight(self.root)
        self.session: Optional[CaptureSession] = None
        self.selected: Optional[WindowInfo | MonitorInfo] = None
        self.crop: Optional[CropRect] = None
        self._pick_armed = False
        self._windows: list[WindowInfo] = []
        self._monitors: list[MonitorInfo] = []
        # Parallel to listbox rows: ("monitor"|"window", info)
        self._targets: list[tuple[str, object]] = []

        self._build_ui()
        self.refresh_targets()

        self.mirror.set_frameless(self.present_var.get())

        self.hotkeys = HotkeyManager(
            on_toggle_pause=self.toggle_pause,
            on_reselect=self.arm_click_pick,
        )
        self.hotkeys.start()

        # Tray: actions arrive on the tray thread and are marshalled onto Tk
        self._tray_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._tray_hint_shown = False
        self.tray = SystemTray(
            schedule=self._tray_queue.put,
            on_show_panel=self.show_panel,
            on_hide_panel=self.hide_panel,
            on_show_mirror=self.mirror.show,
            on_start=self.start_sharing,
            on_stop=lambda: self.stop_sharing(),
            on_toggle_pause=self.toggle_pause,
            on_reselect=self.arm_click_pick,
            on_quit=self.shutdown,
            is_sharing=lambda: self.session is not None,
            is_paused=lambda: bool(self.session and self.session.paused),
        )
        self.tray.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_panel_close)
        self.root.after(1000, self._watchdog)
        self.root.after(100, self._drain_tray_queue)

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        # --- Header (top) ---
        ttk.Label(
            frm,
            text=APP_NAME,
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w")

        ttk.Label(
            frm,
            text=(
                "Capture a specific window (even when covered), optionally crop it, "
                f'then share the "{MIRROR_TITLE}" window in your meeting app.'
            ),
            wraplength=480,
        ).pack(anchor="w", pady=(0, 8))

        # --- Bottom-pinned elements packed first so they are never clipped ---
        self.status_var = tk.StringVar(
            value="Ready · Hotkeys: Ctrl+Shift+P pause · Ctrl+Shift+R pick window"
        )
        ttk.Label(frm, textvariable=self.status_var, wraplength=480).pack(
            side="bottom", anchor="w", pady=(6, 0)
        )

        actions = ttk.Frame(frm)
        actions.pack(side="bottom", fill="x", pady=(10, 4))
        self.start_btn = ttk.Button(
            actions, text="▶  Start Sharing", command=self.start_sharing
        )
        self.start_btn.pack(side="left", ipadx=8, ipady=2)
        self.pause_btn = ttk.Button(
            actions, text="Pause", command=self.toggle_pause, state="disabled"
        )
        self.pause_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(
            actions, text="Stop", command=self.stop_sharing, state="disabled"
        )
        self.stop_btn.pack(side="left")
        ttk.Button(actions, text="Show mirror", command=self.mirror.show).pack(
            side="right"
        )

        settings = ttk.LabelFrame(frm, text="Settings", padding=8)
        settings.pack(side="bottom", fill="x", pady=(8, 0))

        row = ttk.Frame(settings)
        row.pack(fill="x")
        ttk.Label(row, text="Target FPS").pack(side="left")
        self.fps_var = tk.IntVar(value=20)
        self.fps_spin = ttk.Spinbox(
            row, from_=5, to=60, width=5, textvariable=self.fps_var
        )
        self.fps_spin.pack(side="left", padx=8)

        ttk.Label(row, text="Quality").pack(side="left", padx=(16, 0))
        self.quality_var = tk.StringVar(value="Balanced (1440p)")
        self._quality_caps = {
            "Performance (1080p)": 1080,
            "Balanced (1440p)": 1440,
            "High (2160p)": 2160,
            "Full (no cap)": 0,
        }
        quality_combo = ttk.Combobox(
            row,
            width=18,
            state="readonly",
            textvariable=self.quality_var,
            values=list(self._quality_caps.keys()),
        )
        quality_combo.pack(side="left", padx=8)
        quality_combo.bind("<<ComboboxSelected>>", self._on_quality)
        self.topmost_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row,
            text="Mirror always on top",
            variable=self.topmost_var,
            command=self._on_topmost,
        ).pack(side="left", padx=12)
        self.cursor_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            settings,
            text="Show mouse cursor (incl. text I-beam)",
            variable=self.cursor_var,
        ).pack(anchor="w", pady=(4, 0))

        self.present_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            settings,
            text="Presentation mode (hide mirror title bar — share only the region)",
            variable=self.present_var,
            command=self._on_present_mode,
        ).pack(anchor="w", pady=(4, 0))

        crop_frame = ttk.LabelFrame(frm, text="Region crop", padding=8)
        crop_frame.pack(side="bottom", fill="x", pady=8)
        self.crop_label = ttk.Label(crop_frame, text="Full window (no crop)")
        self.crop_label.pack(side="left", fill="x", expand=True)
        ttk.Button(crop_frame, text="Set crop…", command=self.set_crop).pack(
            side="right"
        )
        ttk.Button(crop_frame, text="Clear", command=self.clear_crop).pack(
            side="right", padx=6
        )

        # --- Target list (fills remaining middle space) ---
        list_frame = ttk.LabelFrame(
            frm, text="Target — display or window", padding=8
        )
        list_frame.pack(fill="both", expand=True)

        btn_row = ttk.Frame(list_frame)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Refresh", command=self.refresh_targets).pack(
            side="left"
        )
        ttk.Button(
            btn_row, text="Click to pick…", command=self.arm_click_pick
        ).pack(side="left", padx=6)

        self.listbox = tk.Listbox(list_frame, height=8, exportselection=False)
        self.listbox.pack(fill="both", expand=True, pady=6)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

    def refresh_targets(self) -> None:
        exclude = {int(self.root.winfo_id()), int(self.mirror.win.winfo_id())}
        self._monitors = list_monitors()
        self._windows = list_windows(exclude_hwnds=exclude)
        self._targets = [("monitor", m) for m in self._monitors]
        self._targets += [("window", w) for w in self._windows]

        self.listbox.delete(0, tk.END)
        for kind, info in self._targets:
            self.listbox.insert(tk.END, info.display_name)
        self.status_var.set(
            f"Found {len(self._monitors)} displays, {len(self._windows)} windows"
        )

    def _on_select(self, _event: object = None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        _kind, info = self._targets[sel[0]]
        self.selected = info  # type: ignore[assignment]
        self.status_var.set(f"Selected: {info.display_name}")
        self._highlight_selected()

    def _selected_is_monitor(self) -> bool:
        return isinstance(self.selected, MonitorInfo)

    def _selected_screen_rect(self) -> Optional[tuple[int, int, int, int]]:
        if self.selected is None:
            return None
        if self._selected_is_monitor():
            m: MonitorInfo = self.selected  # type: ignore[assignment]
            return (m.left, m.top, m.right, m.bottom)
        w: WindowInfo = self.selected  # type: ignore[assignment]
        if not is_window_alive(w.hwnd):
            return None
        try:
            return get_window_rect(w.hwnd)
        except Exception:
            return None

    def _highlight_selected(self) -> None:
        rect = self._selected_screen_rect()
        if rect is not None:
            self.highlighter.show(rect)

    def arm_click_pick(self) -> None:
        self._pick_armed = True
        self.status_var.set(
            "Click the target window within 5 seconds… (Ctrl+Shift+R)"
        )
        self.root.iconify()
        self.mirror.win.withdraw()
        threading.Thread(target=self._click_pick_worker, daemon=True).start()

    def _click_pick_worker(self) -> None:
        deadline = time.time() + 5.0
        last_down = False
        while time.time() < deadline:
            down = win32api.GetAsyncKeyState(win32con.VK_LBUTTON) < 0
            if down and not last_down:
                x, y = win32api.GetCursorPos()
                hwnd = get_root_window(window_from_point(x, y))
                title = win32gui.GetWindowText(hwnd)
                if hwnd and title and title != MIRROR_TITLE:
                    info = WindowInfo(
                        hwnd=hwnd,
                        title=title,
                        class_name=win32gui.GetClassName(hwnd),
                        pid=0,
                    )
                    self.root.after(0, lambda i=info: self._apply_picked(i))
                    return
            last_down = down
            time.sleep(0.03)
        self.root.after(0, self._pick_timeout)

    def _apply_picked(self, info: WindowInfo) -> None:
        self._pick_armed = False
        self.root.deiconify()
        self.mirror.show()
        self.refresh_targets()
        # Select matching hwnd if present, else insert at top
        idx = next(
            (
                i
                for i, (kind, w) in enumerate(self._targets)
                if kind == "window" and getattr(w, "hwnd", None) == info.hwnd
            ),
            -1,
        )
        if idx < 0:
            self._targets.insert(0, ("window", info))
            self.listbox.insert(0, info.display_name)
            idx = 0
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(idx)
        self.listbox.see(idx)
        self.selected = self._targets[idx][1]  # type: ignore[assignment]
        self.status_var.set(f"Picked: {info.title}")
        self._highlight_selected()

    def _pick_timeout(self) -> None:
        self._pick_armed = False
        self.root.deiconify()
        self.mirror.show()
        self.status_var.set("Window pick timed out")

    def set_crop(self) -> None:
        if self.selected is None:
            messagebox.showinfo(APP_NAME, "Select a target first.")
            return

        def done(crop) -> None:
            if crop is Ellipsis:
                self.status_var.set("Crop cancelled — keeping previous region")
                return  # Esc — keep previous crop
            self.crop = crop
            self._update_crop_label()
            if self.session is not None:
                self.session.set_crop(self.crop)
            if crop is None:
                self.status_var.set("Crop cleared — sharing full target")
            else:
                self.status_var.set(
                    f"Crop applied: {crop.width}×{crop.height}. "
                    "Start Sharing (or it's live if already sharing)."
                )

        if self._selected_is_monitor():
            mon: MonitorInfo = self.selected  # type: ignore[assignment]
            CropOverlay.for_monitor(
                self.root,
                (mon.left, mon.top, mon.right, mon.bottom),
                on_done=done,
            )
        else:
            win: WindowInfo = self.selected  # type: ignore[assignment]
            if not is_window_alive(win.hwnd):
                messagebox.showinfo(APP_NAME, "Target window is no longer available.")
                return
            CropOverlay.for_window(self.root, win.hwnd, on_done=done)

    def clear_crop(self) -> None:
        self.crop = None
        self._update_crop_label()
        if self.session is not None:
            self.session.set_crop(None)

    def _update_crop_label(self) -> None:
        if self.crop is None:
            self.crop_label.configure(text="Full target (no crop)")
        else:
            c = self.crop
            self.crop_label.configure(
                text=f"Crop: {c.width}×{c.height} at ({c.x}, {c.y})"
            )

    def _on_topmost(self) -> None:
        self.mirror.set_always_on_top(self.topmost_var.get())

    def _on_present_mode(self) -> None:
        self.mirror.set_frameless(self.present_var.get())

    def _current_cap(self) -> Optional[int]:
        cap = self._quality_caps.get(self.quality_var.get(), 1440)
        return cap if cap else None

    def _on_quality(self, _event: object = None) -> None:
        if self.session is not None:
            self.session.max_output_dim = self._current_cap()
        self.status_var.set(f"Quality: {self.quality_var.get()}")

    def _drain_tray_queue(self) -> None:
        while True:
            try:
                action = self._tray_queue.get_nowait()
            except queue.Empty:
                break
            try:
                action()
            except Exception:
                logger.exception("Tray action failed")
        self.root.after(100, self._drain_tray_queue)

    def show_panel(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_panel(self) -> None:
        self.root.withdraw()

    def _on_panel_close(self) -> None:
        # Closing the control panel minimizes to tray instead of quitting.
        self.hide_panel()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.notify(
                "Still running in the tray. Right-click the icon to quit."
            )

    def start_sharing(self) -> None:
        if self.selected is None:
            messagebox.showinfo(APP_NAME, "Select a valid target first.")
            return

        is_monitor = self._selected_is_monitor()
        if not is_monitor and not is_window_alive(self.selected.hwnd):  # type: ignore[union-attr]
            messagebox.showinfo(APP_NAME, "Select a valid target window first.")
            return

        self.stop_sharing(silent=True)
        self.highlighter.hide()  # never capture the confirmation border
        self.mirror.show()
        self.mirror.clear()
        self.mirror.request_fit()  # size window to region aspect (no black bars)

        def on_frame(rgb) -> None:
            self.mirror.push_frame(rgb)

        if is_monitor:
            mon: MonitorInfo = self.selected  # type: ignore[assignment]
            self.session = CaptureSession(
                None,
                on_frame,
                monitor_index=mon.wgc_index,
                monitor_rect=(mon.left, mon.top, mon.right, mon.bottom),
                crop=self.crop,
                target_fps=int(self.fps_var.get()),
                capture_cursor=self.cursor_var.get(),
                draw_border=False,
                max_output_dim=self._current_cap(),
            )
            target_label = mon.display_name
        else:
            win: WindowInfo = self.selected  # type: ignore[assignment]
            self.session = CaptureSession(
                win.hwnd,
                on_frame,
                crop=self.crop,
                target_fps=int(self.fps_var.get()),
                capture_cursor=self.cursor_var.get(),
                draw_border=False,
                max_output_dim=self._current_cap(),
            )
            target_label = win.title

        try:
            backend = self.session.start()
        except Exception as exc:
            logger.exception("Start failed")
            messagebox.showerror(APP_NAME, f"Could not start capture:\n{exc}")
            self.session = None
            return

        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="Pause")
        self.stop_btn.configure(state="normal")
        self.status_var.set(
            f"Sharing “{target_label}” via {backend.upper()} · "
            f'Share window "{MIRROR_TITLE}" in your meeting app'
        )
        self._update_tray()

    def stop_sharing(self, silent: bool = False) -> None:
        if self.session is not None:
            self.session.stop()
            self.session = None
        self.mirror.clear()
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="Pause")
        self.stop_btn.configure(state="disabled")
        if not silent:
            self.status_var.set("Stopped")
        self._update_tray()

    def toggle_pause(self) -> None:
        if self.session is None:
            return
        paused = not self.session.paused
        self.session.set_paused(paused)
        self.pause_btn.configure(text="Resume" if paused else "Pause")
        self.status_var.set("Paused" if paused else "Sharing resumed")
        self._update_tray()

    def _update_tray(self) -> None:
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.update()

    def _watchdog(self) -> None:
        if self.session is not None and self.selected is not None:
            window_gone = (
                not self._selected_is_monitor()
                and not is_window_alive(self.selected.hwnd)  # type: ignore[union-attr]
            )
            if window_gone:
                self.stop_sharing(silent=True)
                self.status_var.set("Target window closed — sharing stopped")
            else:
                # Keep FPS in sync if user changed spinbox
                try:
                    fps = int(self.fps_var.get())
                    self.session.set_target_fps(fps)
                except Exception:
                    pass
        self.root.after(1000, self._watchdog)

    def shutdown(self) -> None:
        self.hotkeys.stop()
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.stop()
        self.highlighter.hide()
        self.stop_sharing(silent=True)
        self.mirror.destroy()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    App().run()
