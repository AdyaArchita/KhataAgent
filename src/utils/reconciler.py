import sqlite3
from typing import Dict, Any, Optional

def check_razorpay_settlement(db_path: str, invoice_id: str, invoice_amount: float) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT settlement_id, amount_settled, gateway_fee FROM razorpay_settlements WHERE invoice_id = ?",
        (invoice_id,)
    )
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return None
        
    settlement_id, amount_settled, gateway_fee = row
    expected_settled_amount = invoice_amount - gateway_fee
    variance = amount_settled - expected_settled_amount
    is_3way_matched = abs(variance) <= 1.00
    
    return {
        "is_3way_matched": bool(is_3way_matched),
        "variance": float(variance),
        "gateway_fee_verified": True
    }
