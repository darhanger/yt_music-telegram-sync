from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from tkinter import messagebox

from . import __version__
from .config import AppConfig, ConfigurationError, default_config_path
from .localization import translate
from .logging_setup import configure_logging
from .service import ServiceStatus, SyncApplicationService
from .setup_wizard import run_setup
from .single_instance import SingleInstance
from .tray import TrayController

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-music-telegram-sync",
        description="Last.fm -> Telegram music sync",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="открыть мастер настройки")
    mode.add_argument("--tray", action="store_true", help="работать в системном трее")
    mode.add_argument("--console", action="store_true", help="работать в консоли")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--restart-wait", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_windows_streams()
    args = build_parser().parse_args(argv)
    console = bool(args.console or (not args.tray and not args.setup))
    configure_logging(console=console)

    if args.setup:
        return 0 if run_setup(args.config) else 1
    if args.restart_wait:
        time.sleep(2.0)

    try:
        config = AppConfig.load(args.config)
    except ConfigurationError as exc:
        log.warning("%s", exc)
        if not run_setup(args.config):
            return 1
        try:
            config = AppConfig.load(args.config)
        except ConfigurationError as second_exc:
            _show_error(str(second_exc), console)
            return 1

    with SingleInstance() as instance:
        if instance.already_running:
            _show_error(
                translate("app.already_running", config.ui_language),
                console,
            )
            return 2
        service = SyncApplicationService(
            config, status_callback=_console_status if console else None
        )
        if args.tray:
            TrayController(service, config_path=args.config).run()
            return 0
        return _run_console(service)


def _run_console(service: SyncApplicationService) -> int:
    service.start()
    try:
        while service.is_alive:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("Получен Ctrl+C")
    finally:
        service.stop()
    return 1 if service.status.kind == "error" else 0


def _console_status(status: ServiceStatus) -> None:
    if status.kind == "error":
        log.error("%s", status.message)


def _show_error(message: str, console: bool) -> None:
    if console:
        print(message, file=sys.stderr)
    else:
        messagebox.showerror("YT Music → Telegram", message)


def _configure_windows_streams() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
