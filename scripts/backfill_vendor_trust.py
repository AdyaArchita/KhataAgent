#!/usr/bin/env python3
import sqlite3
import sys
from pathlib import Path

# Add src to path so we can import controller
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from controller.vendor_trust import VendorTrustStore

def main():
    print("Backfilling Vendor Trust scores from existing audit_log...")
    db_path = Path(__file__).resolve().parent.parent / "data" / "synthetic_ledger.db"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    trust_store = VendorTrustStore()
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN vendor_tier TEXT DEFAULT 'STANDARD'")
        conn.execute("ALTER TABLE audit_log ADD COLUMN requires_human_review BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Already exist

    # Replay all non-eval runs chronologically
    runs = conn.execute("""
        SELECT a.run_id, a.ledger_id, a.match_status, a.created_at, l.vendor_name, l.invoice_number
        FROM audit_log a
        JOIN ledger l ON a.ledger_id = l.ledger_id
        WHERE a.run_source IS NULL OR a.run_source != 'eval_batch'
        ORDER BY a.created_at ASC
    """).fetchall()
    
    # Store runs in a list of dicts so we can close the connection
    runs_data = [dict(run) for run in runs]
    conn.close()

    for run in runs_data:
        vendor_name = run["vendor_name"]
        match_status = run["match_status"]
        
        # Determine previous state to decide tier update
        if match_status == "MATCH":
            trust_store.record_clean_match(vendor_name, vendor_name)
        else:
            severity = "HIGH"
            if match_status == "PARTIAL_MATCH":
                severity = "MEDIUM"
            elif match_status == "SYSTEM_FAILURE":
                severity = "LOW"
            trust_store.record_exception(
                vendor_id=vendor_name,
                vendor_name=vendor_name,
                invoice_id=run["invoice_number"] or run["ledger_id"],
                exception_type=match_status,
                severity=severity
            )
            
        tier = trust_store.get_tier(vendor_name)
        requires_review = (tier == "MANDATORY_AUDIT")
        
        upd_conn = sqlite3.connect(str(db_path), timeout=10.0)
        with upd_conn:
            upd_conn.execute("""
                UPDATE audit_log
                SET vendor_tier = ?, requires_human_review = ?
                WHERE run_id = ?
            """, (tier, requires_review, run["run_id"]))
        upd_conn.close()

    print(f"Successfully backfilled trust scores for {len(runs_data)} runs.")

if __name__ == "__main__":
    main()
