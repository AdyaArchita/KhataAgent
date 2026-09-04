import pytest
import sqlite3
import tempfile
import os
from utils.duplicate_detector import check_duplicate_invoice

@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE ledger (
            ledger_id TEXT,
            vendor_name TEXT,
            gstin TEXT,
            invoice_number TEXT,
            amount REAL,
            invoice_date TEXT
        )
    """)
    # Insert the conflicting records
    cur.execute("""
        INSERT INTO ledger (ledger_id, vendor_name, gstin, invoice_number, amount, invoice_date)
        VALUES ('record105', 'Vendor A (Shared)', '29AABCI5678A1Z5', 'INV-2024-SHARED-999', 1000.0, '2024-04-30')
    """)
    cur.execute("""
        INSERT INTO ledger (ledger_id, vendor_name, gstin, invoice_number, amount, invoice_date)
        VALUES ('record106', 'Vendor B (Shared)', '29AABCW3456D1Z8', 'INV-2024-SHARED-999', 1000.0, '2024-04-30')
    """)
    conn.commit()
    conn.close()
    
    yield path
    os.remove(path)

def test_check_duplicate_invoice_shared_invoice_number(test_db):
    incoming_invoice_a = {
        "ledger_id": "new-a",
        "vendor_name": "Vendor A (Shared)",
        "gstin": "29AABCI5678A1Z5",
        "invoice_number": "INV-2024-SHARED-999",
        "amount": 1000.0,
        "invoice_date": "2024-04-30"
    }
    # This should return CRITICAL because Vendor A matches record105
    res_a = check_duplicate_invoice(test_db, incoming_invoice_a)
    assert res_a is not None
    assert res_a["risk_level"] == "CRITICAL"
    assert res_a["ledger_reference_id"] == "record105"

    incoming_invoice_c = {
        "ledger_id": "new-c",
        "vendor_name": "Vendor C (Shared)",
        "gstin": "29ZZZ",
        "invoice_number": "INV-2024-SHARED-999",
        "amount": 1000.0,
        "invoice_date": "2024-04-30"
    }
    # This should return None because even though invoice_number matches, vendor/gstin don't
    res_c = check_duplicate_invoice(test_db, incoming_invoice_c)
    assert res_c is None
