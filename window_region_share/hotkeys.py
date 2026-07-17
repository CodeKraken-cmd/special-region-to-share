"""Global hotkeys for pause / reselect."""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(
        self,
        *,
        on_toggle_pause: Callable[[], None],
        on_reselect: Callable[[], None],
    ) -> None:
        self.on_toggle_pause = on_toggle_pause
        self.on_reselect = on_reselect
        self._listener = None

    def start(self) -> None:
        try:
            from pynput import keyboard
        except ImportError:
            logger.warning("pynput not available; hotkeys disabled")
            return

        hotkeys = {
            "<ctrl>+<shift>+p": self._safe(self.on_toggle_pause),
            "<ctrl>+<shift>+r": self._safe(self.on_reselect),
        }
        self._listener = keyboard.GlobalHotKeys(hotkeys)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                logger.exception("Error stopping hotkeys")
            self._listener = None

    @staticmethod
    def _safe(fn: Callable[[], None]) -> Callable[[], None]:
        def wrapper() -> None:
            try:
                fn()
            except Exception:
                logger.exception("Hotkey handler error")

        return wrapper
