"""Pydantic v2 schemas for the KhataAgent reconciliation LangGraph state."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.contracts import (
    AnomalyFlag,
    DuplicateRisk,
    EvidenceContract,
    GstinValidation,
)
from utils.audit_trail import LineageStep


class MatchStatus(str, Enum):
    """Lifecycle status of a single reconciliation run."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    PENDING = "PENDING"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    NON_DETERMINISTIC_FAILURE = "NON_DETERMINISTIC_FAILURE"


class Discrepancy(str, Enum):
    """Specific financial discrepancy types.

    Values are grouped by the pipeline layer that produces them.
    Add new values here AND to generate_dataset.py's disc_type→enum map.
    """

    # ── original values (kept for backward-compat) ───────────────────
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    TAX_MISMATCH = "TAX_MISMATCH"
    MISSING_LINE = "MISSING_LINE"
    RAZORPAY_SETTLEMENT_MISMATCH = "RAZORPAY_SETTLEMENT_MISMATCH"
    DUPLICATE = "DUPLICATE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    GSTIN_MISMATCH = "GSTIN_MISMATCH"

    # ── gateway & settlement ──────────────────────────────────────────
    RAZORPAY_FEE_MISMATCH           = "RAZORPAY_FEE_MISMATCH"
    SETTLEMENT_CURRENCY_FX_MISMATCH = "SETTLEMENT_CURRENCY_FX_MISMATCH"
    SETTLEMENT_OVERPAYMENT          = "SETTLEMENT_OVERPAYMENT"
    SETTLEMENT_MISSING              = "SETTLEMENT_MISSING"

    # ── invoice lifecycle ─────────────────────────────────────────────
    ORPHAN_CREDIT_NOTE              = "ORPHAN_CREDIT_NOTE"
    DOCUMENT_TYPE_MISMATCH          = "DOCUMENT_TYPE_MISMATCH"
    BROKEN_AMENDMENT_CHAIN          = "BROKEN_AMENDMENT_CHAIN"
    IRN_VALIDATION_FAILURE          = "IRN_VALIDATION_FAILURE"

    # ── regulatory compliance ─────────────────────────────────────────
    RCM_CLASSIFICATION_ERROR        = "RCM_CLASSIFICATION_ERROR"
    GSTIN_SCHEME_MISMATCH           = "GSTIN_SCHEME_MISMATCH"
    ITC_PERIOD_MISMATCH             = "ITC_PERIOD_MISMATCH"
    SEZ_TAX_VIOLATION               = "SEZ_TAX_VIOLATION"

    # ── fraud & identity ──────────────────────────────────────────────
    PAN_GSTIN_SPOOF_MISMATCH        = "PAN_GSTIN_SPOOF_MISMATCH"

    # ── tax classification ────────────────────────────────────────────
    HSN_RATE_MISMATCH               = "HSN_RATE_MISMATCH"
    TCS_WITHHOLDING_MISMATCH        = "TCS_WITHHOLDING_MISMATCH"
    CESS_COMPONENT_MISMATCH         = "CESS_COMPONENT_MISMATCH"
    TDS_WITHHOLDING_MISMATCH        = "TDS_WITHHOLDING_MISMATCH"

    # ── legal / document ──────────────────────────────────────────────
    LEGAL_TEXT_AMOUNT_MISMATCH      = "LEGAL_TEXT_AMOUNT_MISMATCH"

    # ── LLM & sandbox ────────────────────────────────────────────────
    ADVERSARIAL_INJECTION_ATTEMPT   = "ADVERSARIAL_INJECTION_ATTEMPT"
    CONTEXT_WINDOW_EXHAUSTION       = "CONTEXT_WINDOW_EXHAUSTION"
    CONTEXT_TRUNCATION_FAILURE      = "CONTEXT_TRUNCATION_FAILURE"
    ZERO_VALUE_DIV_ERROR            = "ZERO_VALUE_DIV_ERROR"
    MASKED_TAX_RATE_MISMATCH        = "MASKED_TAX_RATE_MISMATCH"
    MARKDOWN_STRIP_FAILURE          = "MARKDOWN_STRIP_FAILURE"
    SYNTAX_BOOLEAN_TYPE_ERROR       = "SYNTAX_BOOLEAN_TYPE_ERROR"

    # ── parser & serialisation ────────────────────────────────────────
    PARSER_EXTRACTION_DRIFT         = "PARSER_EXTRACTION_DRIFT"
    DATE_FORMAT_AMBIGUITY           = "DATE_FORMAT_AMBIGUITY"
    LINEAGE_SERIALIZATION_DRIFT     = "LINEAGE_SERIALIZATION_DRIFT"

    # ── statistical anomaly ───────────────────────────────────────────
    ANOMALY_DETECTOR_SUPPRESSED     = "ANOMALY_DETECTOR_SUPPRESSED"
    BENFORD_LAW_VIOLATION           = "BENFORD_LAW_VIOLATION"

    # ── temporal & timezone ───────────────────────────────────────────
    TIMEZONE_BOUNDARY_SHIFT         = "TIMEZONE_BOUNDARY_SHIFT"
    FUTURE_DATED_INVOICE            = "FUTURE_DATED_INVOICE"

    # ── data poisoning & serialisation limits ─────────────────────────
    NON_FINITE_FLOAT_CRASH          = "NON_FINITE_FLOAT_CRASH"
    EMPTY_CONTEXT_HALLUCINATION     = "EMPTY_CONTEXT_HALLUCINATION"
    DB_COLUMN_TRUNCATION            = "DB_COLUMN_TRUNCATION"

    # ── orchestration & infrastructure ───────────────────────────────
    GRAPH_RECURSION_LIMIT_EXCEEDED  = "GRAPH_RECURSION_LIMIT_EXCEEDED"
    CONCURRENCY_OVERWRITE_DETECTED  = "CONCURRENCY_OVERWRITE_DETECTED"
    BACKDATED_LEDGER_ENTRY          = "BACKDATED_LEDGER_ENTRY"

    # ── enterprise statutory & compliance edge cases ──────────────────
    BLOCKED_ITC_CLAIM_ERROR          = "BLOCKED_ITC_CLAIM_ERROR"
    INACTIVE_SUSPENDED_GSTIN_ERROR   = "INACTIVE_SUSPENDED_GSTIN_ERROR"
    CREDIT_NOTE_VALUE_EXHAUSTION     = "CREDIT_NOTE_VALUE_EXHAUSTION"
    AGGREGATION_ORDER_OF_OPERATIONS  = "AGGREGATION_ORDER_OF_OPERATIONS"
    MULTI_PAGE_CONTEXT_MISALIGNMENT  = "MULTI_PAGE_CONTEXT_MISALIGNMENT"


VendorTier = Literal["STANDARD", "ENHANCED", "MANDATORY_AUDIT"]
ClearanceState = Literal[
    "AUTO_CLEARED",
    "PENDING_HUMAN_AUDIT",
    "MANUALLY_RELEASED",
    "BLOCKED",
]


class LineItem(BaseModel):
    """A single line item on an invoice or ledger entry."""

    model_config = ConfigDict(extra="forbid")

    description: str
    quantity: float
    unit_price: float
    amount: float


class TransactionData(BaseModel):
    """Structured representation of a single invoice / transaction."""

    model_config = ConfigDict(extra="ignore")

    ledger_id: str
    vendor_name: str = ""
    invoice_number: str = ""
    amount: float = 0.0
    tax_amount: float = 0.0
    tax_rate: float = 0.0
    gstin: str = ""
    currency: str = "INR"
    line_items: list[LineItem] = Field(default_factory=list)
    invoice_date: str = ""
    raw_invoice_text: str = ""

    @field_validator('*', mode='before')
    @classmethod
    def reject_non_finite_floats(cls, v):
        import math
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise ValueError("NON_FINITE_FLOAT_CRASH")
        if isinstance(v, str) and v.lower() in ['nan', 'inf', '-inf', 'infinity', '-infinity']:
            raise ValueError("NON_FINITE_FLOAT_CRASH")
        return v


class ReconciliationState(BaseModel):
    """Top-level LangGraph state for one reconciliation run."""

    model_config = ConfigDict(validate_assignment=True)

    # ── identity ─────────────────────────────────────────────────────
    run_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique run identifier (UUID4) for audit linkage.",
    )

    # ── input data ───────────────────────────────────────────────────
    transaction: TransactionData = Field(
        ...,
        description="Parsed invoice data.",
    )

    # ── ledger lookup ────────────────────────────────────────────────
    ledger_record: dict[str, Any] | None = Field(
        default=None,
        description="Matching row from the SQLite ledger.",
    )

    # ── retrieval (Chroma stub) ──────────────────────────────────────
    retrieved_context_ids: list[str] = Field(
        default_factory=list,
        description="Document IDs returned by vector similarity search.",
    )

    # ── Quant Agent outputs ──────────────────────────────────────────
    generated_code: str | None = Field(
        default=None,
        description="Python snippet generated by QuantAgent.",
    )
    execution_result: dict[str, Any] | None = Field(
        default=None,
        description="Parsed JSON stdout from sandboxed execution.",
    )

    # ── reconciliation result ────────────────────────────────────────
    match_status: MatchStatus = Field(
        default=MatchStatus.PENDING,
        description="Lifecycle status after reconciliation.",
    )
    discrepancies: list[Discrepancy] = Field(
        default_factory=list,
        description="Financial discrepancy types diagnosed.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Deterministic confidence score.",
    )

    # ── trust & routing ──────────────────────────────────────────────
    vendor_tier: VendorTier = Field(
        default="STANDARD",
        description="Vendor trust tier.",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Flag indicating if the invoice requires human review.",
    )

    # ── exception / failure reasons ──────────────────────────────────
    exception_reason: str | None = Field(
        default=None,
        description="Human-readable explanation of the financial exception.",
    )
    system_failure_reason: str | None = Field(
        default=None,
        description="Non-financial failure description (sandbox, timeout, AST, etc.).",
    )

    # ── observability & contracts ────────────────────────────────────
    token_usage: dict[str, int] = Field(
        default_factory=dict,
        description="LLM token counts.",
    )
    latency_ms: float = Field(
        default=0.0,
        description="Wall-clock latency in milliseconds.",
    )
    evidence_contract: EvidenceContract | None = Field(
        default=None,
        description="Machine-readable evidence contract.",
    )
    duplicate_risk: DuplicateRisk | None = Field(
        default=None,
        description="Duplicate risk payload if found.",
    )
    gstin_validation: GstinValidation | None = Field(
        default=None,
        description="Structural validation result of the invoice GSTIN.",
    )
    anomaly_flag: AnomalyFlag | None = Field(
        default=None,
        description="Deterministic statistical anomaly flag.",
    )
    audit_lineage: list[LineageStep] = Field(
        default_factory=list,
        description="Immutable lineage matrix of execution steps.",
    )
    clearance_state: ClearanceState = Field(
        default="PENDING_HUMAN_AUDIT",
        description="HITL clearance state.",
    )
    self_consistency: bool | None = Field(
        default=None,
        description="Whether the self-consistency replay passed.",
    )
    replay_delta: float | None = Field(
        default=None,
        description="Delta between original and replay executions.",
    )