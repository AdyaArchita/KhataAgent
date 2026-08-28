import statistics

def compute_baseline(amounts: list[float]) -> dict:
    """
    Computes a deterministic statistical baseline for anomaly detection.
    Uses Median and Median Absolute Deviation (MAD) to avoid sensitivity to outliers.
    """
    if not amounts:
        return {"median": 0.0, "mad": 0.0}
    
    median = statistics.median(amounts)
    mad = statistics.median([abs(a - median) for a in amounts])
    return {"median": median, "mad": mad}

def check_anomaly(amount: float, baseline: dict, threshold_multiplier: float = 3.0) -> dict:
    """
    Flags an invoice amount as an anomaly if it exceeds the baseline by the given multiplier.
    Returns:
    {"is_anomaly": bool, "reason": str | None}
    This is explicitly a deterministic statistical flag, not an ML anomaly score.
    """
    median = baseline.get("median", 0.0)
    mad = baseline.get("mad", 0.0)
    
    if mad == 0.0:
        return {"is_anomaly": False, "reason": None}
    
    deviation = abs(amount - median)
    if deviation > threshold_multiplier * mad:
        reason = f"Amount {amount} is statistically anomalous (STATISTICAL_OUTLIER). It deviates from the median ({median}) by more than {threshold_multiplier}x the Median Absolute Deviation ({mad})."
        return {"is_anomaly": True, "reason": reason}
    
    return {"is_anomaly": False, "reason": None}

import sqlite3
import os
from pathlib import Path

_BASELINE_CACHE = None

def get_global_baseline(db_path: str = 'data/synthetic_ledger.db') -> dict:
    global _BASELINE_CACHE
    if _BASELINE_CACHE is not None:
        return _BASELINE_CACHE
        
    if not os.path.exists(db_path):
        return {'median': 0.0, 'mad': 0.0}
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT amount FROM ledger')
        amounts = [r[0] for r in cursor.fetchall()]
        conn.close()
        
        _BASELINE_CACHE = compute_baseline(amounts)
        return _BASELINE_CACHE
    except Exception:
        return {'median': 0.0, 'mad': 0.0}
