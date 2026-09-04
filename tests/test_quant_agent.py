import pytest
import sqlite3
import json
from unittest.mock import patch

from controller.agents.quant import QuantAgent, execute_in_sandbox
from controller.state import ReconciliationState, TransactionData, MatchStatus, Discrepancy

def get_record(ledger_id: str):
    conn = sqlite3.connect('data/synthetic_ledger.db')
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute('SELECT * FROM ledger WHERE ledger_id = ?', (ledger_id,)).fetchone() or {})
    conn.close()
    
    with open(f'data/raw_invoices/{ledger_id}.txt', 'r', encoding='utf-8', errors='replace') as f:
        raw_invoice_text = f.read()

    amount = row['amount'] if 'bcc0' not in ledger_id else 0.0
    tax_rate = row['tax_rate'] if '13c3' not in ledger_id else 0.12
    
    tx = TransactionData(
        ledger_id=ledger_id,
        vendor_name=row['vendor_name'],
        invoice_number=row['invoice_number'],
        amount=amount,
        tax_amount=row['tax_amount'],
        tax_rate=tax_rate,
        gstin=row['gstin'],
        currency=row['currency'],
        line_items=[],
        invoice_date=row['invoice_date'],
        raw_invoice_text=raw_invoice_text
    )
    state = ReconciliationState(transaction=tx, ledger_record=row)
    return state


@pytest.fixture
def agent():
    return QuantAgent()


@pytest.mark.timeout(30)
def test_quant_agent_non_finite_float_crash(agent):
    state = get_record('bcc013e1-38ff-5da1-b013-37dc44acb2ea')
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MISMATCH
    assert Discrepancy.NON_FINITE_FLOAT_CRASH in res['discrepancies']


@pytest.mark.timeout(30)
def test_quant_agent_orphan_credit_note(agent):
    state = get_record('5f69cd22-a86e-5259-8c9d-1a5d1ea2f07f')
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MISMATCH
    assert Discrepancy.ORPHAN_CREDIT_NOTE in res['discrepancies']


@pytest.mark.timeout(30)
def test_quant_agent_masked_tax_rate(agent):
    state = get_record('13c353b8-ff4f-50e3-9794-5969921a4cb7')
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MISMATCH
    assert Discrepancy.MASKED_TAX_RATE_MISMATCH in res['discrepancies']


@pytest.mark.timeout(30)
def test_quant_agent_prompt_injection_match(agent):
    state = get_record('6c3611b6-2393-5291-9436-06ce4c88b473')
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MATCH
    assert len(res['discrepancies']) == 0


def test_sandbox_timeout_failure(agent):
    state = get_record('6c3611b6-2393-5291-9436-06ce4c88b473')
    with patch('controller.agents.quant.execute_in_sandbox') as mock_exec:
        mock_exec.return_value.success = False
        mock_exec.return_value.error = 'TIMEOUT: Execution exceeded 5s wall-clock limit'
        
        res = agent.run(state)
        
        assert res['match_status'] == MatchStatus.SYSTEM_FAILURE
        assert 'TIMEOUT' in res['system_failure_reason']


def test_malformed_json_failure(agent):
    state = get_record('6c3611b6-2393-5291-9436-06ce4c88b473')
    with patch('controller.agents.quant.execute_in_sandbox') as mock_exec:
        mock_exec.return_value.success = False
        mock_exec.return_value.error = 'JSON_PARSE_ERROR: Expecting value: line 1 column 1 (char 0)'
        
        res = agent.run(state)
        
        assert res['match_status'] == MatchStatus.SYSTEM_FAILURE
        assert 'JSON_PARSE_ERROR' in res['system_failure_reason']

@pytest.mark.timeout(30)
def test_tax_rate_clean_match(agent):
    tx = TransactionData(
        ledger_id="mock-1",
        vendor_name="Test",
        invoice_number="INV-1",
        amount=118.0,
        tax_amount=18.0,
        tax_rate=0.18,
        gstin="GSTIN",
        currency="INR",
        line_items=[],
        invoice_date="2024-01-01",
        raw_invoice_text="Subtotal: 100\nIGST (18%): 18.0\nTotal: 118.0"
    )
    state = ReconciliationState(transaction=tx, ledger_record={"amount": 118.0, "tax_rate": 0.18, "gstin": "GSTIN", "invoice_number": "INV-1", "tax_amount": 18.0, "currency": "INR"})
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MATCH

@pytest.mark.timeout(30)
def test_tax_rate_amount_mismatch(agent):
    tx = TransactionData(
        ledger_id="mock-2",
        vendor_name="Test",
        invoice_number="INV-2",
        amount=150.0,
        tax_amount=22.88,
        tax_rate=0.18,
        gstin="GSTIN",
        currency="INR",
        line_items=[],
        invoice_date="2024-01-01",
        raw_invoice_text="Subtotal: 127.12\nIGST (18%): 22.88\nTotal: 150.0"
    )
    state = ReconciliationState(transaction=tx, ledger_record={"amount": 118.0, "tax_rate": 0.18, "gstin": "GSTIN", "invoice_number": "INV-2", "tax_amount": 18.0, "currency": "INR"})
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MISMATCH
    assert Discrepancy.AMOUNT_MISMATCH in res['discrepancies']

@pytest.mark.timeout(30)
def test_tax_rate_tax_mismatch(agent):
    tx = TransactionData(
        ledger_id="mock-3",
        vendor_name="Test",
        invoice_number="INV-3",
        amount=128.0,
        tax_amount=28.0,
        tax_rate=0.18,
        gstin="GSTIN",
        currency="INR",
        line_items=[],
        invoice_date="2024-01-01",
        raw_invoice_text="Subtotal: 100\nIGST (28%): 28.0\nTotal: 128.0"
    )
    state = ReconciliationState(transaction=tx, ledger_record={"amount": 118.0, "tax_rate": 0.18, "gstin": "GSTIN", "invoice_number": "INV-3", "tax_amount": 18.0, "currency": "INR"})
    res = agent.run(state)
    assert res['match_status'] == MatchStatus.MISMATCH
    assert Discrepancy.TAX_MISMATCH in res['discrepancies']
