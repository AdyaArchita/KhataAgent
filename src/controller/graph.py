"""LangGraph state machine for the KhataAgent reconciliation pipeline.

Graph topology (strictly linear, no cycles)
────────────────────────────────────────────
  START → supervisor_router
        → document_parser
        → quant_agent
        → [conditional]
             ├─ MATCH          → END
             └─ otherwise      → exception_handler → END

The graph always terminates by construction — there is no retry loop
and no ``max_steps`` counter.

Audit persistence happens in ``run_pipeline()`` *after* the graph
returns, keeping the graph topology exactly as specified.

Entry point
───────────
  ``run_pipeline(invoice_path, ledger_id) -> ReconciliationState``
  builds the initial state, executes the compiled graph, persists the
  audit row, and returns the final state.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from controller.agents.quant import QuantAgent
from controller.vendor_trust import VendorTrustStore
from controller.state import (
    Discrepancy,
    LineItem,
    MatchStatus,
    ReconciliationState,
    TransactionData,
)

load_dotenv()
logger = logging.getLogger(__name__)

# ── paths ────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = _DATA_DIR / "synthetic_ledger.db"
_CHROMA_DIR = _DATA_DIR / "chroma"

# Singleton QuantAgent (loads LLM once)
_quant_agent: QuantAgent | None = None


def _get_quant_agent() -> QuantAgent:
    global _quant_agent
    if _quant_agent is None:
        _quant_agent = QuantAgent()
    return _quant_agent


# ══════════════════════════════════════════════════════════════════════
# NODES
# ══════════════════════════════════════════════════════════════════════


# ── 1. Supervisor Router ─────────────────────────────────────────────

def supervisor_router(state: ReconciliationState) -> dict[str, Any]:
    """Supervisor that routes to DocumentParser and performs trust checks.
    
    Checks the vendor's temporal trust profile and flags the invoice for
    deep audit if the vendor tier is MANDATORY_AUDIT.
    """
    try:
        ledger_id = state.transaction.ledger_id
        logger.info("SupervisorRouter: routing ledger_id=%s", ledger_id)
        
        # 1. Fetch vendor_name to use as vendor_id
        # NOTE: Using vendor_name as vendor_id is a prototype shortcut. 
        # In production, use GSTIN or a stable internal vendor ID to prevent 
        # naming collisions or renaming attacks.
        ledger_record = _fetch_ledger_row(ledger_id)
        vendor_name = ledger_record["vendor_name"] if ledger_record else "UNKNOWN"
        
        # 2. Check Temporal Trust Routing
        updates: dict[str, Any] = {}
        routing_enabled = os.getenv("VENDOR_TRUST_ROUTING", "true").lower() == "true"
        if routing_enabled and vendor_name != "UNKNOWN":
            trust_store = VendorTrustStore()
            tier = trust_store.get_tier(vendor_name)
            updates["vendor_tier"] = tier
            if tier == "MANDATORY_AUDIT":
                updates["requires_human_review"] = True
                logger.warning(
                    "SupervisorRouter: ledger_id=%s flagged for MANDATORY_AUDIT "
                    "(vendor=%s)", ledger_id, vendor_name
                )
            elif tier == "ENHANCED":
                logger.info("SupervisorRouter: vendor=%s has ENHANCED trust tier", vendor_name)
        
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        step = LineageStep(
            step_name="supervisor_router",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary=f"Input: ledger_id={state.transaction.ledger_id}",
            output_summary="Routed to document_parser"
        )
        updates["audit_lineage"] = state.audit_lineage + [step]
        
        return updates
    except Exception as exc:
        logger.exception("SupervisorRouter failed")
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        step = LineageStep(
            step_name="supervisor_router",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary=f"Input: ledger_id={state.transaction.ledger_id}",
            output_summary=f"FAILED: {exc}"
        )
        return {
            "match_status": MatchStatus.SYSTEM_FAILURE,
            "confidence": 0.0,
            "system_failure_reason": f"Routing failed: {exc}",
            "audit_lineage": state.audit_lineage + [step]
        }


# ── 2. Document Parser ──────────────────────────────────────────────

def document_parser(state: ReconciliationState) -> dict[str, Any]:
    """Extract structured numbers from raw invoice text + fetch ledger row.

    Responsibilities:
      1. Parse the unstructured invoice text into structured fields
         (amount, tax, GSTIN, line items, etc.).
      2. Fetch the matching ledger row from SQLite by ``ledger_id``.
      3. Embed the invoice text and query Chroma (stub for future
         extension) — populates ``retrieved_context_ids`` but the match
         decision is driven solely by the deterministic QuantAgent.

    The raw invoice text is stored in state as *data* — it is never
    concatenated into an LLM instruction string.
    """
    try:
        return _document_parser_inner(state)
    except Exception as exc:
        logger.exception("DocumentParser failed")
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        step = LineageStep(
            step_name="document_parser",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary="Extracted text from invoice",
            output_summary=f"FAILED: {exc}"
        )
        return {
            "match_status": MatchStatus.SYSTEM_FAILURE,
            "confidence": 0.0,
            "system_failure_reason": f"DocumentParser error: {exc}",
            "audit_lineage": state.audit_lineage + [step]
        }


def _document_parser_inner(state: ReconciliationState) -> dict[str, Any]:
    raw_text = state.transaction.raw_invoice_text
    ledger_id = state.transaction.ledger_id

    # ── Phase 1.1: Empty Context Guard ───────────────────────────────
    if not raw_text or not raw_text.strip():
        logger.error("DocumentParser received empty invoice text for ledger_id=%s.", ledger_id)
        return {
            "match_status": MatchStatus.MISMATCH,
            "confidence": 1.0,
            "discrepancies": [Discrepancy.EMPTY_CONTEXT_HALLUCINATION],
            "system_failure_reason": "0-byte file intercepted",
        }

    # ── Phase 1.1b: Non-finite Value Guard ───────────────────────────
    import re
    if re.search(r"(?:TOTAL|CGST|SGST|IGST)[^\n]*?\b(NaN|Infinity|-Infinity)\b",
                 raw_text, re.IGNORECASE):
        logger.error("Non-finite value detected in invoice text for ledger_id=%s.", ledger_id)
        return {
            "match_status": MatchStatus.MISMATCH,
            "confidence": 1.0,
            "discrepancies": [Discrepancy.NON_FINITE_FLOAT_CRASH],
            "system_failure_reason": "Non-finite value (NaN/Infinity) detected in invoice text",
        }

    # ── Phase 1.2: Removed Adversarial Injection Firewall ────────────────
    # We let the LLM handle the text natively to test if it resists the injection.

    # ── 1. Parse invoice text ────────────────────────────────────────
    parsed = _parse_invoice_text(raw_text)
    line_items = [
        LineItem(**item) for item in parsed.get("line_items", [])
    ]

    from pydantic import ValidationError
    try:
        updated_transaction = TransactionData.model_validate({
            **state.transaction.model_dump(),
            "vendor_name": parsed.get("vendor_name", ""),
            "invoice_number": parsed.get("invoice_number", ""),
            "amount": parsed.get("amount", 0.0),
            "tax_amount": parsed.get("tax_amount", 0.0),
            "tax_rate": parsed.get("tax_rate", 0.0),
            "gstin": parsed.get("gstin", ""),
            "currency": parsed.get("currency", "INR"),
            "line_items": [item for item in parsed.get("line_items", [])],
            "invoice_date": parsed.get("invoice_date", ""),
        })
    except ValidationError as e:
        if "NON_FINITE_FLOAT_CRASH" in str(e):
            return {
                "match_status": MatchStatus.MISMATCH,
                "discrepancies": [Discrepancy.NON_FINITE_FLOAT_CRASH],
                "system_failure_reason": "NaN/Infinity injection caught by Pydantic"
            }
        raise

    # ── 2b. Fetch ledger record from SQLite ──────────────────────────
    ledger_record = _fetch_ledger_row(ledger_id)
    if ledger_record is None:
        logger.warning("No ledger row found for ledger_id=%s", ledger_id)
        return {
            "transaction": updated_transaction,
            "match_status": MatchStatus.SYSTEM_FAILURE,
            "confidence": 0.0,
            "system_failure_reason": f"Ledger row not found: {ledger_id}",
        }

    # ── 2c. Chroma retrieval (stub for future extension) ─────────────
    retrieved_ids = _chroma_retrieve(raw_text)

    logger.info(
        "DocumentParser: parsed invoice for ledger_id=%s "
        "(amount=%.2f, tax=%.2f, %d line items, %d context IDs)",
        ledger_id,
        updated_transaction.amount,
        updated_transaction.tax_amount,
        len(line_items),
        len(retrieved_ids),
    )

    from utils.audit_trail import LineageStep
    from datetime import datetime, UTC
    step = LineageStep(
        step_name="document_parser",
        timestamp=datetime.now(UTC).isoformat(),
        input_summary="Extracted text from invoice",
        output_summary=f"Parsed {len(line_items)} line items. Amount: {updated_transaction.amount}"
    )

    return {
        "transaction": updated_transaction,
        "ledger_record": ledger_record,
        "retrieved_context_ids": retrieved_ids,
        "audit_lineage": state.audit_lineage + [step]
    }


def _parse_invoice_text(text: str) -> dict[str, Any]:
    """Deterministic regex parser for the synthetic invoice format.

    This works reliably on our generated invoices.  For production use,
    this would be replaced with an LLM-based document extraction step.
    """
    result: dict[str, Any] = {}

    # Vendor name (first GSTIN line belongs to vendor, second to buyer)
    m = re.search(r"Vendor:\s*(.+)", text)
    if m:
        result["vendor_name"] = m.group(1).strip()

    # Vendor GSTIN (first occurrence)
    m = re.search(r"GSTIN:\s*(\S+)", text)
    if m:
        result["gstin"] = m.group(1).strip()

    m = re.search(r"Invoice No:\s*(.+)", text)
    if m:
        result["invoice_number"] = m.group(1).strip()

    m = re.search(r"Date:\s*(\S+)", text)
    if m:
        result["invoice_date"] = m.group(1).strip()

    # Currency
    m = re.search(r"Currency:\s*(\w+)", text)
    if m:
        result["currency"] = m.group(1).strip()

    # Line items — pattern uses re.DOTALL so the description can span the
    # injected-newline adversarial noise; we then strip the description to
    # the first line only to recover the canonical item name.
    item_pattern = (
        r"(\d+)\.\s+([\s\S]+?)\s*-\s*Qty:\s*([\d.]+)\s*x\s*"
        r"(?:Rs\.|₹)?\s*([\d,]+\.?\d*)\s*=\s*(?:Rs\.|₹)?\s*([\d,]+\.?\d*)"
    )
    line_items: list[dict] = []
    for match in re.finditer(item_pattern, text):
        # Strip the description to its first line, discarding any injected text
        raw_desc = match.group(2).strip()
        clean_desc = raw_desc.splitlines()[0].strip()
        line_items.append(
            {
                "description": clean_desc,
                "quantity": float(match.group(3)),
                "unit_price": float(match.group(4).replace(",", "")),
                "amount": float(match.group(5).replace(",", "")),
            }
        )
    result["line_items"] = line_items

    # Subtotal
    subtotal = 0.0
    m = re.search(r"Subtotal:\s*(?:Rs\.|₹)?\s*([\d,]+\.?\d*)", text)
    if m:
        subtotal = float(m.group(1).replace(",", ""))

    # Total Tax
    m = re.search(r"Total Tax:\s*(?:Rs\.|₹)?\s*([\d,]+\.?\d*)", text)
    if m:
        result["tax_amount"] = float(m.group(1).replace(",", ""))

    # Tax rate (derived from subtotal and tax amount)
    if subtotal > 0 and "tax_amount" in result:
        result["tax_rate"] = round(result["tax_amount"] / subtotal, 2)

    # TOTAL
    m = re.search(r"TOTAL:\s*(?:Rs\.|₹)?\s*([\d,]+\.?\d*)", text)
    if m:
        result["amount"] = float(m.group(1).replace(",", ""))

    return result


def _fetch_ledger_row(ledger_id: str) -> dict[str, Any] | None:
    """Fetch a single row from the ``ledger`` table by primary key."""
    if not _DB_PATH.exists():
        logger.error("Ledger database not found: %s", _DB_PATH)
        return None

    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")  # allow concurrent SSE reads during eval writes
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM ledger WHERE ledger_id = ?", (ledger_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _chroma_retrieve(text: str, n_results: int = 5) -> list[str]:
    """Embed invoice text and query the local Chroma collection.

    This is a *stub for future extension*: the retrieved IDs are stored
    in state but the match decision is driven solely by the QuantAgent.
    Failures are non-fatal — returns an empty list on any error.
    """
    try:
        import chromadb
        from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.debug("No GEMINI_API_KEY — skipping Chroma retrieval")
            return []

        if not _CHROMA_DIR.exists():
            logger.debug("Chroma directory not found — skipping retrieval")
            return []

        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        embedding_fn = GoogleGenerativeAiEmbeddingFunction(
            api_key=api_key,
        )
        collection = client.get_or_create_collection(
            name="invoices",
            embedding_function=embedding_fn,  # type: ignore[arg-type]
        )

        from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
        def _is_429(exc: BaseException) -> bool:
            return "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc) or "ResourceExhausted" in str(exc)

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=10, min=10, max=60),
            retry=retry_if_exception(_is_429),
            reraise=True
        )
        def _execute_query():
            return collection.query(
                query_texts=[text],
                n_results=n_results,
            )
            
        results = _execute_query()
        return results.get("ids", [[]])[0]

    except Exception as exc:  # noqa: BLE001
        logger.warning("Chroma retrieval failed (non-fatal): %s", exc)
        return []


# ── 3. Quant Agent node ─────────────────────────────────────────────

def quant_agent_node(state: ReconciliationState) -> dict[str, Any]:
    """LangGraph node wrapper around QuantAgent.

    If a previous node already set ``SYSTEM_FAILURE``, skip execution
    and pass through — the error boundary was already tripped.
    """
    try:
        if state.match_status in (MatchStatus.SYSTEM_FAILURE, MatchStatus.NON_DETERMINISTIC_FAILURE):
            logger.info("QuantAgent skipped — prior SYSTEM_FAILURE")
            return {}

        agent = _get_quant_agent()
        res = agent.run(state)
        
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        code_exec = res.get("generated_code")
        step = LineageStep(
            step_name="quant_agent",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary="Execute agent against extracted fields",
            output_summary=f"Status: {res.get('match_status')}",
            code_executed=code_exec
        )
        res["audit_lineage"] = state.audit_lineage + [step]
        return res
    except Exception as exc:
        logger.exception("QuantAgent node failed")
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        step = LineageStep(
            step_name="quant_agent",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary="Execute agent against extracted fields",
            output_summary=f"FAILED: {exc}"
        )
        return {
            "match_status": MatchStatus.SYSTEM_FAILURE,
            "confidence": 0.0,
            "system_failure_reason": f"QuantAgent node error: {exc}",
            "audit_lineage": state.audit_lineage + [step]
        }


# ── 4. Exception Handler ────────────────────────────────────────────

def exception_handler(state: ReconciliationState) -> dict[str, Any]:
    """Format a human-readable exception reason from the discrepancies.

    This node runs for any non-MATCH outcome: MISMATCH, PARTIAL_MATCH,
    or SYSTEM_FAILURE.  It assembles a narrative explanation suitable
    for the audit trail and downstream dashboards.
    """
    try:
        return _exception_handler_inner(state)
    except Exception as exc:
        logger.exception("ExceptionHandler failed")
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        step = LineageStep(
            step_name="exception_handler",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary="Handling exceptions",
            output_summary=f"FAILED: {exc}"
        )
        return {
            "system_failure_reason": (
                state.system_failure_reason
                or f"ExceptionHandler error: {exc}"
            ),
            "audit_lineage": state.audit_lineage + [step]
        }


def _exception_handler_inner(state: ReconciliationState) -> dict[str, Any]:
    if state.match_status in (MatchStatus.SYSTEM_FAILURE, MatchStatus.NON_DETERMINISTIC_FAILURE):
        raw_reason = state.system_failure_reason or ""
        # --- Phase 3: Exception Sanitization ---
        if "429" in raw_reason or "RESOURCE_EXHAUSTED" in raw_reason:
            raw_reason = "AI Compute Limit Exceeded: Service rate limit throttled. Please retry."
            
        reason = (
            f"System failure during reconciliation of "
            f"ledger_id={state.transaction.ledger_id}: "
            f"{raw_reason}"
        )
        logger.warning("ExceptionHandler (SYSTEM_FAILURE): %s", reason)
        from utils.audit_trail import LineageStep
        from datetime import datetime, UTC
        step = LineageStep(
            step_name="exception_handler",
            timestamp=datetime.now(UTC).isoformat(),
            input_summary="Handling SYSTEM_FAILURE",
            output_summary=f"Reason: {reason}"
        )
        return {
            "exception_reason": reason, 
            "system_failure_reason": raw_reason,
            "audit_lineage": state.audit_lineage + [step]
        }

    # ── build narrative from discrepancies ───────────────────────────
    parts: list[str] = []
    result = state.execution_result or {}

    for d in state.discrepancies:
        if d == Discrepancy.AMOUNT_MISMATCH:
            diff = result.get("amount_difference", "?")
            parts.append(
                f"Amount mismatch: invoice={result.get('invoice_amount', '?')}, "
                f"ledger={result.get('ledger_amount', '?')}, diff=Rs. {diff}"
            )
        elif d == Discrepancy.TAX_MISMATCH:
            parts.append(
                f"Tax mismatch: tax diff=Rs. {result.get('tax_difference', '?')}, "
                f"rate match={result.get('tax_rate_match', '?')}"
            )
        elif d == Discrepancy.GSTIN_MISMATCH:
            parts.append("GSTIN does not match between invoice and ledger")
        elif d == Discrepancy.CURRENCY_MISMATCH:
            parts.append("Currency mismatch between invoice and ledger")
        elif d == Discrepancy.MISSING_LINE:
            parts.append(
                f"{result.get('line_items_missing', '?')} ledger line item(s) "
                f"missing from invoice"
            )
        elif d == Discrepancy.DUPLICATE:
            parts.append(
                f"{result.get('line_items_extra', '?')} extra/duplicate line "
                f"item(s) on invoice"
            )
        elif d == Discrepancy.MASKED_TAX_RATE_MISMATCH:
            parts.append("Masked tax rate mismatch detected")
        elif d == Discrepancy.EMPTY_CONTEXT_HALLUCINATION:
            parts.append("Empty context hallucination detected")
        elif d == Discrepancy.NON_FINITE_FLOAT_CRASH:
            parts.append("Non-finite float crash detected")
        elif d == Discrepancy.ORPHAN_CREDIT_NOTE:
            parts.append("Orphan credit note detected")

    status_label = state.match_status.value
    reason = (
        f"[{status_label}] Reconciliation exception for "
        f"ledger_id={state.transaction.ledger_id} "
        f"(confidence={state.confidence}): {'; '.join(parts)}"
    )
    logger.info("ExceptionHandler: %s", reason)
    
    from utils.audit_trail import LineageStep
    from datetime import datetime, UTC
    step = LineageStep(
        step_name="exception_handler",
        timestamp=datetime.now(UTC).isoformat(),
        input_summary=f"Discrepancies: {[d.value for d in state.discrepancies]}",
        output_summary=f"Reason: {reason}"
    )
    return {"exception_reason": reason, "audit_lineage": state.audit_lineage + [step]}


# ══════════════════════════════════════════════════════════════════════
# ROUTING
# ══════════════════════════════════════════════════════════════════════

def _route_after_quant(state: ReconciliationState) -> str:
    """Conditional edge after QuantAgent.

    MATCH → END (the record reconciled cleanly).
    Everything else → exception_handler (mismatch, partial, or failure).
    """
    if state.match_status == MatchStatus.MATCH:
        return "end"
    return "exception_handler"


# ══════════════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """Construct and return the (uncompiled) reconciliation state graph.

    Topology:
      START → supervisor → document_parser → quant_agent
                                                ├─ MATCH → END
                                                └─ else  → exception_handler → END
    """
    graph = StateGraph(ReconciliationState)

    # ── nodes ────────────────────────────────────────────────────────
    graph.add_node("supervisor", supervisor_router)
    graph.add_node("document_parser", document_parser)
    graph.add_node("quant_agent", quant_agent_node)
    graph.add_node("exception_handler", exception_handler)

    # ── edges (strictly linear, no cycles) ───────────────────────────
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", "document_parser")
    graph.add_edge("document_parser", "quant_agent")
    graph.add_conditional_edges(
        "quant_agent",
        _route_after_quant,
        {"end": END, "exception_handler": "exception_handler"},
    )
    graph.add_edge("exception_handler", END)

    return graph


# ══════════════════════════════════════════════════════════════════════
# AUDIT PERSISTENCE
# ══════════════════════════════════════════════════════════════════════

def persist_audit_log(state: ReconciliationState, run_source: str = "manual", batch_id: str | None = None) -> None:
    """Write the final reconciliation state to the ``audit_log`` table.

    Called by ``run_pipeline`` after the graph terminates.  The audit
    trail is NOT allowed to exist only in memory (constraint 6).
    """
    # ── Update Vendor Trust ──────────────────────────────────────────
    if run_source != "eval_batch" and state.transaction.vendor_name:
        try:
            trust_store = VendorTrustStore()
            vendor_name = state.transaction.vendor_name
            # NOTE: Same tradeoff as above, using vendor_name as the ID.
            if state.match_status == MatchStatus.MATCH:
                trust_store.record_clean_match(vendor_name, vendor_name)
            else:
                severity = "HIGH"
                if state.match_status == MatchStatus.PARTIAL_MATCH:
                    severity = "MEDIUM"
                elif state.match_status in (MatchStatus.SYSTEM_FAILURE, MatchStatus.NON_DETERMINISTIC_FAILURE):
                    severity = "LOW"
                    
                trust_store.record_exception(
                    vendor_id=vendor_name,
                    vendor_name=vendor_name,
                    invoice_id=state.transaction.invoice_number or state.transaction.ledger_id,
                    exception_type=state.match_status.value,
                    severity=severity
                )
        except Exception as exc:
            logger.error("Failed to record vendor trust: %s", exc)

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        try:
            conn.execute("ALTER TABLE audit_log ADD COLUMN vendor_tier TEXT DEFAULT 'STANDARD'")
            conn.execute("ALTER TABLE audit_log ADD COLUMN requires_human_review BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Columns already exist

        try:
            conn.execute("ALTER TABLE audit_log ADD COLUMN evidence_contract TEXT")
        except sqlite3.OperationalError:
            pass # Column already exists

        try:
            conn.execute("ALTER TABLE audit_log ADD COLUMN run_source TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE audit_log ADD COLUMN batch_id TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE audit_log ADD COLUMN clearance_state TEXT")
        except sqlite3.OperationalError:
            pass

        conn.execute(
            """
            INSERT OR REPLACE INTO audit_log
            (run_id, ledger_id, match_status, confidence, discrepancies,
             exception_reason, system_failure_reason, generated_code,
             execution_result, token_usage, latency_ms, created_at, run_source, batch_id, vendor_tier, requires_human_review, evidence_contract, clearance_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.run_id,
                state.transaction.ledger_id,
                state.match_status.value,
                state.confidence,
                json.dumps([d.value for d in state.discrepancies]),
                state.exception_reason,
                state.system_failure_reason,
                state.generated_code,
                json.dumps(state.execution_result) if state.execution_result else None,
                json.dumps(state.token_usage),
                state.latency_ms,
                datetime.now(UTC).isoformat(),
                run_source,
                batch_id,
                state.vendor_tier,
                state.requires_human_review,
                state.evidence_contract.model_dump_json() if hasattr(state.evidence_contract, "model_dump_json") else (json.dumps(state.evidence_contract) if state.evidence_contract else None),
                state.clearance_state,
            ),
        )
        conn.commit()
        logger.info(
            "Audit log persisted: run_id=%s, status=%s, confidence=%.2f",
            state.run_id,
            state.match_status.value,
            state.confidence,
        )
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT  (fix #2 — explicit initial-state construction)
# ══════════════════════════════════════════════════════════════════════

def run_pipeline(
    invoice_path: str,
    ledger_id: str,
    run_source: str = "manual",
    batch_id: str | None = None,
) -> ReconciliationState:
    """Run a single invoice through the full reconciliation graph.

    This is the canonical entry point for both programmatic use and
    the future FastAPI endpoint.

    Args:
        invoice_path: Filesystem path to an unstructured invoice text file.
        ledger_id:    Foreign key matching a row in the ``ledger`` table.
        run_source:   Origin of the run (e.g. manual, eval_batch).
        batch_id:     Optional batch identifier for eval runs.

    Returns:
        The final ``ReconciliationState`` after the graph terminates
        and the audit row has been persisted.
    """
    # ── read invoice ─────────────────────────────────────────────────
    raw_text = Path(invoice_path).read_text(encoding="utf-8")

    # ── check duplicates ──────────────────────────────────────────────
    import sys
    # Add project root to sys.path if not present so utils is accessible
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        
    from utils.duplicate_detector import check_duplicate_invoice
    parsed_invoice = _parse_invoice_text(raw_text)
    parsed_invoice["ledger_id"] = ledger_id
    duplicate_risk = check_duplicate_invoice(str(_DB_PATH), parsed_invoice)

    # ── build initial state ──────────────────────────────────────────
    initial_state = ReconciliationState(
        transaction=TransactionData(
            ledger_id=ledger_id,
            raw_invoice_text=raw_text,
        ),
        duplicate_risk=duplicate_risk,
    )

    # ── compile & run ────────────────────────────────────────────────
    graph = build_graph()
    compiled = graph.compile()

    t0 = time.perf_counter()
    result = compiled.invoke(initial_state.model_dump())
    latency_ms = (time.perf_counter() - t0) * 1000

    # ── hydrate final state ──────────────────────────────────────────
    if isinstance(result, ReconciliationState):
        final_state = result
    else:
        final_state = ReconciliationState.model_validate(result)

    from utils.gstin_validator import validate_gstin
    from utils.anomaly_detector import get_global_baseline, check_anomaly

    gstin_val = None
    if final_state.transaction.gstin:
        gstin_val = validate_gstin(final_state.transaction.gstin)
        final_state = final_state.model_copy(update={"gstin_validation": gstin_val})
        
    anomaly_flag = None
    if final_state.transaction.amount > 0:
        baseline = get_global_baseline(str(_DB_PATH))
        anomaly_flag = check_anomaly(final_state.transaction.amount, baseline)
        final_state = final_state.model_copy(update={"anomaly_flag": anomaly_flag})

    # Stamp total pipeline latency
    final_state = final_state.model_copy(update={"latency_ms": latency_ms})

    # ── compute 3-way match ──────────────────────────────────────────
    from utils.reconciler import check_razorpay_settlement
    three_way_match = None
    if final_state.ledger_record and final_state.match_status != MatchStatus.SYSTEM_FAILURE:
        if Discrepancy.EMPTY_CONTEXT_HALLUCINATION not in final_state.discrepancies and Discrepancy.NON_FINITE_FLOAT_CRASH not in final_state.discrepancies:
            three_way_match = check_razorpay_settlement(
                str(_DB_PATH),
                final_state.transaction.ledger_id,
                final_state.ledger_record["amount"]
            )
    
    # ── compute clearance state ──────────────────────────────────────
    clearance_state = "AUTO_CLEARED"
    if final_state.match_status != MatchStatus.MATCH or (anomaly_flag and anomaly_flag.get("is_anomaly") if isinstance(anomaly_flag, dict) else (anomaly_flag.is_anomaly if anomaly_flag else False)):
        clearance_state = "PENDING_HUMAN_AUDIT"
        
    if three_way_match and not three_way_match["is_3way_matched"]:
        final_state.discrepancies.append(Discrepancy.RAZORPAY_SETTLEMENT_MISMATCH) if hasattr(Discrepancy, 'RAZORPAY_SETTLEMENT_MISMATCH') else None
        final_state.match_status = MatchStatus.MISMATCH
        clearance_state = "PENDING_HUMAN_AUDIT"
        
    if final_state.duplicate_risk is not None:
        if hasattr(Discrepancy, 'DUPLICATE_INVOICE'):
            final_state.discrepancies.append(Discrepancy.DUPLICATE_INVOICE)
            final_state.match_status = MatchStatus.MISMATCH
        clearance_state = "PENDING_HUMAN_AUDIT"
    
    # ── build evidence contract ──────────────────────────────────────
    execution_result = final_state.execution_result or {}
    
    if "amount_difference" in execution_result:
        diff = float(execution_result["amount_difference"])
        tolerance_check = abs(diff) <= 0.01
    else:
        tolerance_check = (final_state.match_status == MatchStatus.MATCH)
        
    from models.contracts import EvidenceContract
    _all_disc_codes = [d.value for d in final_state.discrepancies]
    contract = EvidenceContract(
        ledger_id=final_state.transaction.ledger_id,
        vendor_id=final_state.transaction.vendor_name or None,
        retrieved_context_ids=final_state.retrieved_context_ids,
        generated_code=final_state.generated_code,
        execution_result=execution_result,
        tolerance_check=tolerance_check,
        # Full list — no multi-discrepancy invoice loses data (fix 28c)
        discrepancy_codes=_all_disc_codes,
        # Deprecated single-value kept for backward-compat with existing consumers
        discrepancy_code=_all_disc_codes[0] if _all_disc_codes else None,
        confidence=final_state.confidence,
        vendor_trust_tier=final_state.vendor_tier,
        duplicate_risk=final_state.duplicate_risk,
        gstin_validation=final_state.gstin_validation,
        anomaly_flag=final_state.anomaly_flag,
        audit_lineage=final_state.audit_lineage,
        clearance_state=clearance_state,
        three_way_match=three_way_match,
        self_consistency=final_state.self_consistency,
        replay_delta=final_state.replay_delta,
        timestamp=datetime.now(UTC).isoformat()
    )
    final_state = final_state.model_copy(update={"evidence_contract": contract, "clearance_state": clearance_state})

    # ── persist audit log (constraint 6) ─────────────────────────────
    persist_audit_log(final_state, run_source, batch_id)

    return final_state


# ══════════════════════════════════════════════════════════════════════
# END-TO-END SMOKE TEST  (fix #4 — genuine e2e verification)
# ══════════════════════════════════════════════════════════════════════

def _smoke_test() -> None:
    """Run two invoices through the full pipeline and assert results.

    Requires:
      - ``data/synthetic_ledger.db`` to exist (run generate_dataset.py first)
      - ``data/raw_invoices/`` with invoice text files
      - ``GEMINI_API_KEY`` in environment / ``.env``

    Verifies:
      1. A known clean-match invoice → MATCH, confidence=1.0
      2. A known discrepancy invoice → MISMATCH or PARTIAL_MATCH,
         confidence > 0.0
      3. Both runs produce an audit_log row in SQLite
    """
    import uuid as _uuid_mod

    manifest_path = _DATA_DIR / "manifest.json"
    if not manifest_path.exists():
        print("ERROR: Run `scripts/generate_dataset.py` first.")
        return

    manifest = json.loads(manifest_path.read_text())
    print(f"Loaded manifest: {manifest['total']} records (seed={manifest['seed']})")

    # ── pick a known-clean record (index 0) and a known-discrepancy ──
    # Use the same deterministic UUID generation as the dataset
    clean_id = str(_uuid_mod.uuid5(_uuid_mod.NAMESPACE_DNS, "khata-42-0"))
    disc_id = str(_uuid_mod.uuid5(_uuid_mod.NAMESPACE_DNS, "khata-42-55"))

    invoices_dir = _DATA_DIR / "raw_invoices"

    # ── test 1: clean match ──────────────────────────────────────────
    clean_path = invoices_dir / f"{clean_id}.txt"
    if not clean_path.exists():
        print(f"ERROR: Invoice file not found: {clean_path}")
        return

    print(f"\n=== Test 1: Clean match (ledger_id={clean_id[:8]}...) ===")
    result1 = run_pipeline(str(clean_path), clean_id)
    print(f"  Status:     {result1.match_status.value}")
    print(f"  Confidence: {result1.confidence}")
    print(f"  Latency:    {result1.latency_ms:.0f}ms")
    assert result1.match_status == MatchStatus.MATCH, (
        f"Expected MATCH, got {result1.match_status.value}"
    )
    assert result1.confidence == 1.0, (
        f"Expected confidence=1.0, got {result1.confidence}"
    )
    print("  [PASS]")

    # -- test 2: discrepancy -----------------------------------------
    disc_path = invoices_dir / f"{disc_id}.txt"
    if not disc_path.exists():
        print(f"ERROR: Invoice file not found: {disc_path}")
        return

    print(f"\n=== Test 2: Discrepancy (ledger_id={disc_id[:8]}...) ===")
    result2 = run_pipeline(str(disc_path), disc_id)
    print(f"  Status:       {result2.match_status.value}")
    print(f"  Confidence:   {result2.confidence}")
    print(f"  Discrepancies: {[d.value for d in result2.discrepancies]}")
    print(f"  Exception:    {result2.exception_reason}")
    print(f"  Latency:      {result2.latency_ms:.0f}ms")
    assert result2.match_status in (
        MatchStatus.MISMATCH,
        MatchStatus.PARTIAL_MATCH,
    ), f"Expected MISMATCH or PARTIAL_MATCH, got {result2.match_status.value}"
    assert result2.confidence > 0.0, (
        f"Expected confidence > 0.0, got {result2.confidence}"
    )
    print("  [PASS]")

    # -- test 3: verify audit log ------------------------------------
    print("\n=== Test 3: Audit log verification ===")
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT run_id, ledger_id, match_status, confidence "
        "FROM audit_log ORDER BY created_at DESC LIMIT 2"
    ).fetchall()
    conn.close()

    assert len(rows) >= 2, f"Expected >=2 audit rows, got {len(rows)}"
    for row in rows:
        print(
            f"  audit: run_id={row['run_id'][:8]}... "
            f"status={row['match_status']} conf={row['confidence']}"
        )
    print("  [PASS]")

    print("\n====================================")
    print("  All smoke tests passed!")
    print("====================================")


if __name__ == "__main__":
    _smoke_test()
