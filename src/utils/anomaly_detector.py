"""Deterministic statistical anomaly detection for invoice amounts.

Design constraints
──────────────────
- Uses Median Absolute Deviation (MAD) — robust to outliers.
- ``check_anomaly`` is a pure function: it accepts the baseline as a
  parameter so callers can control caching and avoid module-global state
  poisoning across batch runs (fix 21a / baseline_cache_poisoning).
- ``get_global_baseline`` caches per-db-path, not as a single module-level
  singleton, so different database paths get independent baselines.
"""
from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

# Path-keyed cache: {db_path_str: baseline_dict}
# Using a dict instead of a single module-level value prevents a baseline
# computed from one dataset from poisoning a different evaluation run.
_BASELINE_CACHE: dict[str, dict] = {}


def compute_baseline(amounts: list[float]) -> dict:
    """Compute a deterministic MAD baseline from a list of amounts."""
    if not amounts:
        return {"median": 0.0, "mad": 0.0}

    median = statistics.median(amounts)
    mad = statistics.median([abs(a - median) for a in amounts])
    return {"median": median, "mad": mad}


def check_anomaly(
    amount: float,
    baseline: dict,
    threshold_multiplier: float = 3.0,
) -> dict:
    """Flag an invoice amount as anomalous if it exceeds the MAD threshold.

    Args:
        amount:               The invoice amount to evaluate.
        baseline:             A dict with ``median`` and ``mad`` keys,
                              produced by :func:`compute_baseline` or
                              :func:`get_global_baseline`.  Passed explicitly
                              so callers control caching (fix 21a).
        threshold_multiplier: Number of MAD units before flagging (default 3).

    Returns:
        ``{"is_anomaly": bool, "reason": str | None}``
    """
    median = baseline.get("median", 0.0)
    mad = baseline.get("mad", 0.0)

    if mad == 0.0:
        # All amounts are identical — MAD is zero.
        # Anomaly detection is explicitly disabled in this degenerate case;
        # callers that care about this condition should check mad == 0.0
        # themselves and append Discrepancy.ANOMALY_DETECTOR_SUPPRESSED.
        return {"is_anomaly": False, "reason": None}

    deviation = abs(amount - median)
    if deviation > threshold_multiplier * mad:
        reason = (
            f"Amount {amount} is statistically anomalous (STATISTICAL_OUTLIER). "
            f"It deviates from the median ({median}) by more than "
            f"{threshold_multiplier}x the Median Absolute Deviation ({mad})."
        )
        return {"is_anomaly": True, "reason": reason}

    return {"is_anomaly": False, "reason": None}


def get_global_baseline(db_path: str = "data/synthetic_ledger.db") -> dict:
    """Return the MAD baseline for *db_path*, cached per path.

    Caching is keyed on the resolved absolute path string so that two
    callers using different database files get independent baselines
    (fixes the module-level singleton that poisoned entire eval batches).

    Pass ``db_path`` explicitly in tests to avoid touching the real DB.
    """
    global _BASELINE_CACHE

    resolved = str(Path(db_path).resolve())
    if resolved in _BASELINE_CACHE:
        return _BASELINE_CACHE[resolved]

    if not Path(resolved).exists():
        return {"median": 0.0, "mad": 0.0}

    try:
        conn = sqlite3.connect(resolved)
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM ledger")
        amounts = [r[0] for r in cursor.fetchall()]
        conn.close()

        baseline = compute_baseline(amounts)
        _BASELINE_CACHE[resolved] = baseline
        return baseline
    except Exception:
        return {"median": 0.0, "mad": 0.0}


def invalidate_baseline_cache(db_path: str | None = None) -> None:
    """Evict one or all cached baselines.

    Call this after regenerating the dataset so the next evaluation run
    recomputes the baseline from the new data rather than using stale values.

    Args:
        db_path: If given, evict only that path's cache entry.
                 If None, evict all cached baselines.
    """
    global _BASELINE_CACHE
    if db_path is None:
        _BASELINE_CACHE.clear()
    else:
        _BASELINE_CACHE.pop(str(Path(db_path).resolve()), None)
