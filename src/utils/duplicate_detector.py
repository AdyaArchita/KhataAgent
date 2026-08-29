import sqlite3
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def check_duplicate_invoice(db_path: str, incoming_invoice: dict) -> dict | None:
    vendor_name = incoming_invoice.get("vendor_name")
    gstin = incoming_invoice.get("gstin")
    amount = incoming_invoice.get("amount", 0.0)
    invoice_date_str = incoming_invoice.get("invoice_date")
    current_ledger_id = incoming_invoice.get("ledger_id")

    if not invoice_date_str:
        return None

    try:
        inv_date = datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
    except ValueError:
        # Non-ISO date formats (e.g. "31/03/2024", "04-Mar-2024") cannot be
        # parsed — duplicate detection is DISABLED for this record.
        # Log at WARNING so the failure is observable in the audit trail
        # rather than silently returning None (fix 20c / PARSER_EXTRACTION_DRIFT).
        logger.warning(
            "duplicate_detector: non-ISO invoice_date %r could not be parsed "
            "(expected YYYY-MM-DD). Duplicate detection SKIPPED for this record. "
            "Check _parse_invoice_text for date format normalisation.",
            invoice_date_str,
        )
        return None
        
    start_date = (inv_date - timedelta(days=3)).strftime("%Y-%m-%d")
    end_date = (inv_date + timedelta(days=3)).strftime("%Y-%m-%d")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        query = """
            SELECT ledger_id, amount FROM ledger 
            WHERE (gstin = ? OR vendor_name = ?) 
            AND invoice_date BETWEEN ? AND ?
            AND ledger_id != ?
        """
        rows = conn.execute(query, (gstin or "", vendor_name or "", start_date, end_date, current_ledger_id)).fetchall()
        
        for row in rows:
            if abs(row["amount"] - amount) <= 0.01:
                return {
                    "risk_level": "CRITICAL",
                    "reason": "Duplicate GSTIN/Vendor with same amount and within 3 days.",
                    "ledger_reference_id": row["ledger_id"]
                }
                
        return None
        
    except Exception as e:
        logger.error(f"Duplicate detector error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()
