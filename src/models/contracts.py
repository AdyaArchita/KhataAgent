from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from utils.audit_trail import LineageStep
from typing import Literal

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

class EvidenceContract(BaseModel):
    ledger_id: str
    vendor_id: Optional[str] = None
    retrieved_context_ids: List[str] = Field(default_factory=list)
    generated_code: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None
    tolerance_check: bool
    discrepancy_code: Optional[str] = None
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
