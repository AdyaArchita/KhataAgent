from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from typing import Literal

from utils.audit_trail import LineageStep


def _reject_non_finite(v: float | None) -> float | None:
    """Shared validator: reject NaN and Inf to prevent json.dumps() crash."""
    if v is not None and (math.isnan(v) or math.isinf(v)):
        raise ValueError(
            f"Non-finite float value {v!r} is not JSON-serialisable and "
            "indicates upstream data corruption (NON_FINITE_FLOAT_CRASH)."
        )
    return v


class DuplicateRisk(BaseModel):
    risk_level: Literal["CRITICAL", "WARNING"]
    reason: str
    ledger_reference_id: str


class GstinValidation(BaseModel):
    valid: bool
    reason: Optional[str] = None
    state_code: Optional[str] = None


class AnomalyFlag(BaseModel):
    is_anomaly: bool
    reason: Optional[str] = None


class ThreeWayMatch(BaseModel):
    is_3way_matched: bool
    variance: float
    gateway_fee_verified: bool

    @field_validator("variance", mode="before")
    @classmethod
    def variance_finite(cls, v: float) -> float:
        return _reject_non_finite(v)  # type: ignore[return-value]


class EvidenceContract(BaseModel):
    ledger_id: str
    vendor_id: Optional[str] = None
    retrieved_context_ids: List[str] = Field(default_factory=list)
    generated_code: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None
    tolerance_check: bool

    # Promoted from single Optional[str] → full list so multi-error invoices
    # do not silently lose all but the first discrepancy (error 28c).
    discrepancy_codes: List[str] = Field(
        default_factory=list,
        description="All discrepancy enum values diagnosed for this run.",
    )
    # Kept for backward-compat with existing audit_log JSON blobs.
    discrepancy_code: Optional[str] = Field(
        default=None,
        description="Deprecated: first element of discrepancy_codes. "
                    "Use discrepancy_codes for all new consumers.",
    )

    confidence: float
    vendor_trust_tier: str
    duplicate_risk: Optional[DuplicateRisk] = None
    gstin_validation: Optional[GstinValidation] = None
    anomaly_flag: Optional[AnomalyFlag] = None
    audit_lineage: List[LineageStep] = Field(default_factory=list)
    clearance_state: str = Field(default="PENDING_HUMAN_AUDIT")
    three_way_match: Optional[ThreeWayMatch] = None
    self_consistency: Optional[bool] = None
    replay_delta: Optional[float] = None
    timestamp: str

    # ── NaN / Inf guards on every numeric field ───────────────────────
    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_finite(cls, v: float) -> float:
        return _reject_non_finite(v)  # type: ignore[return-value]

    @field_validator("replay_delta", mode="before")
    @classmethod
    def replay_delta_finite(cls, v: float | None) -> float | None:
        return _reject_non_finite(v)

