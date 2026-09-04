import pytest
from controller.state import ReconciliationState, TransactionData, MatchStatus, Discrepancy
from controller.graph import _document_parser_inner

def test_non_finite_guard_infinity():
    tx = TransactionData(
        ledger_id="test-1",
        vendor_name="Test",
        invoice_number="123",
        amount=0.0,
        tax_amount=0.0,
        tax_rate=0.0,
        gstin="GSTIN",
        currency="INR",
        line_items=[],
        invoice_date="2024-01-01",
        raw_invoice_text="Subtotal: 100\nTOTAL: Infinity\n"
    )
    state = ReconciliationState(transaction=tx)
    result = _document_parser_inner(state)
    assert result["match_status"] == MatchStatus.MISMATCH
    assert Discrepancy.NON_FINITE_FLOAT_CRASH in result["discrepancies"]

def test_non_finite_guard_nan():
    tx = TransactionData(
        ledger_id="test-2",
        vendor_name="Test",
        invoice_number="123",
        amount=0.0,
        tax_amount=0.0,
        tax_rate=0.0,
        gstin="GSTIN",
        currency="INR",
        line_items=[],
        invoice_date="2024-01-01",
        raw_invoice_text="CGST (9%): NaN\nSGST (9%): NaN\nTotal: 100"
    )
    state = ReconciliationState(transaction=tx)
    result = _document_parser_inner(state)
    assert result["match_status"] == MatchStatus.MISMATCH
    assert Discrepancy.NON_FINITE_FLOAT_CRASH in result["discrepancies"]
