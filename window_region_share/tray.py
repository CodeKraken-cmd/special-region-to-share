"""System tray icon and menu.

The tray runs on its own thread (pystray). All menu actions are marshalled back
onto the Tk main thread via a scheduler callback so Tk stays single-threaded.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# Callback bundle: each is a plain no-arg function that performs a Tk action.
Action = Callable[[], None]


def _make_icon_image(size: int = 64) -> Image.Image:
    """A simple 'framed region' glyph for the tray."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # dark rounded background
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=10, fill=(24, 24, 32, 255))
    # cyan region frame
    m = 14
    d.rectangle([m, m, size - m, size - m], outline=(0, 229, 255, 255), width=4)
    # small red "live" dot
    d.ellipse([size - 22, size - 22, size - 10, size - 10], fill=(255, 45, 45, 255))
    return img


class SystemTray:
    def __init__(
        self,
        *,
        schedule: Callable[[Action], None],
        on_show_panel: Action,
        on_hide_panel: Action,
        on_show_mirror: Action,
        on_start: Action,
        on_stop: Action,
        on_toggle_pause: Action,
        on_reselect: Action,
        on_quit: Action,
        is_sharing: Callable[[], bool],
        is_paused: Callable[[], bool],
    ) -> None:
        self._schedule = schedule
        self._on_show_panel = on_show_panel
        self._on_hide_panel = on_hide_panel
        self._on_show_mirror = on_show_mirror
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_toggle_pause = on_toggle_pause
        self._on_reselect = on_reselect
        self._on_quit = on_quit
        self._is_sharing = is_sharing
        self._is_paused = is_paused
        self._icon = None

    def _run(self, action: Action) -> None:
        self._schedule(action)

    def _build(self):
        from pystray import Icon, Menu, MenuItem

        menu = Menu(
            MenuItem(
                "Show control panel",
                lambda: self._run(self._on_show_panel),
                default=True,
            ),
            MenuItem("Hide control panel", lambda: self._run(self._on_hide_panel)),
            MenuItem("Show mirror window", lambda: self._run(self._on_show_mirror)),
            Menu.SEPARATOR,
            MenuItem(
                "Start sharing",
                lambda: self._run(self._on_start),
                visible=lambda item: not self._is_sharing(),
            ),
            MenuItem(
                "Stop sharing",
                lambda: self._run(self._on_stop),
                visible=lambda item: self._is_sharing(),
            ),
            MenuItem(
                lambda item: "Resume" if self._is_paused() else "Pause",
                lambda: self._run(self._on_toggle_pause),
                visible=lambda item: self._is_sharing(),
            ),
            MenuItem("Pick window (click)", lambda: self._run(self._on_reselect)),
            Menu.SEPARATOR,
            MenuItem("Quit", lambda: self._run(self._on_quit)),
        )
        return Icon(
            "special_region_to_share",
            _make_icon_image(),
            "Special Region to Share",
            menu,
        )

    def start(self) -> None:
        try:
            self._icon = self._build()
            # run_detached spawns the tray on its own thread
            self._icon.run_detached()
        except Exception:
            logger.exception("Failed to start system tray")
            self._icon = None

    def update(self) -> None:
        if self._icon is not None:
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def notify(self, message: str, title: str = "Special Region to Share") -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
