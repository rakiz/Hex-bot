from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

_ONE_WEEK = 7 * 24 * 60 * 60


def _loop() -> None:
    while True:
        try:
            from .db import init_week_stats
            init_week_stats()
        except Exception as exc:
            log.warning("Weekly stats job failed: %s", exc)
        time.sleep(_ONE_WEEK)


def start() -> None:
    threading.Thread(target=_loop, daemon=True, name="stats-scheduler").start()
    log.info("Stats scheduler started (weekly interval)")
