from __future__ import annotations

import os
from typing import Self


class SingleInstance:
    def __init__(self, name: str = "YTMusicTelegramSync") -> None:
        self._handle = None
        self.already_running = False
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            self._handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
            self.already_running = kernel32.GetLastError() == 183

    def close(self) -> None:
        if self._handle is not None and os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
