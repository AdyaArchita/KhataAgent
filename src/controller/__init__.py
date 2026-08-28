"""KhataAgent Controller — Multi-Agent Financial Reconciliation Engine.

This package provides the core reconciliation pipeline:
  SupervisorRouter → DocumentParser → QuantAgent → ExceptionHandler

Logging is configured here so every module in the controller package
inherits a consistent format, level, and handler without ad-hoc setup.
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure shared logging for the entire controller package.

    Call once at import time.  Uses ``force=True`` so re-imports or
    test harnesses can safely reconfigure without side-effects.
    """
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


# Auto-configure on first import of the controller package.
setup_logging()
