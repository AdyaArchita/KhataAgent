import json
import sqlite3
import os
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Any, Optional, Literal

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pydantic import BaseModel, constr, Field
from controller.vendor_trust import VendorTrustStore

# ── Paths ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "synthetic_ledger.db"

# ── Pydantic Models ───────────────────────────────────────────────────────
class RunSummary(BaseModel):
    run_id: str
    ledger_id: str
    vendor_name: str
    invoice_number: str
    match_status: str
    confidence: float
    latency_ms: float
    created_at: str
    vendor_tier: str = "STANDARD"
    requires_human_review: bool = False
    evidence_contract: Any = None
    clearance_state: str = "AUTO_CLEARED"

class RunDetail(RunSummary):
    discrepancies: list[str]
    exception_reason: Optional[str] = None
    system_failure_reason: Optional[str] = None
    generated_code: Optional[str] = None
    execution_result: Any

from typing import Literal

class ClearancePayload(BaseModel):
    decision: Literal['approve', 'reject', 'override']
    reason: str = Field(..., min_length=5)
    reviewed_by: str = "demo_user"
    notes: Optional[str] = None

# ── FastAPI App ───────────────────────────────────────────────────────────
app = FastAPI(title="KhataAgent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Database Dependency ───────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ── Endpoints ─────────────────────────────────────────────────────────────
@app.get("/api/runs", response_model=list[RunSummary])
def get_runs(db: sqlite3.Connection = Depends(get_db)):
    if not DB_PATH.exists():
        return []

    try:
        # Check if the most recent record belongs to a batch
        latest = db.execute("SELECT batch_id FROM audit_log ORDER BY created_at DESC LIMIT 1").fetchone()
        if latest and latest["batch_id"]:
            batch_id = latest["batch_id"]
            query = """
                SELECT 
                    a.run_id, a.ledger_id, a.match_status, a.confidence, a.latency_ms, a.created_at,
                    l.vendor_name, l.invoice_number,
                    a.vendor_tier, a.requires_human_review, a.evidence_contract, a.clearance_state
                FROM audit_log a
                JOIN ledger l ON a.ledger_id = l.ledger_id
                WHERE a.batch_id = ?
                ORDER BY a.created_at DESC
            """
            rows = db.execute(query, (batch_id,)).fetchall()
        else:
            query = """
                SELECT 
                    a.run_id, a.ledger_id, a.match_status, a.confidence, a.latency_ms, a.created_at,
                    l.vendor_name, l.invoice_number,
                    a.vendor_tier, a.requires_human_review, a.evidence_contract, a.clearance_state
                FROM audit_log a
                JOIN ledger l ON a.ledger_id = l.ledger_id
                ORDER BY a.created_at DESC
                LIMIT 50
            """
            rows = db.execute(query).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[RunSummary] = []
    for row in rows:
        row_dict = dict(row)
        
        # Override visual status if human review required
        match_status = row_dict["match_status"]
        if row_dict.get("requires_human_review"):
            match_status = "PENDING_REVIEW"
            
        evidence_contract = None
        if row_dict.get("evidence_contract"):
            try:
                evidence_contract = json.loads(row_dict["evidence_contract"])
            except json.JSONDecodeError:
                pass

        results.append(RunSummary(
            run_id=row_dict["run_id"],
            ledger_id=row_dict["ledger_id"],
            vendor_name=row_dict["vendor_name"],
            invoice_number=row_dict["invoice_number"],
            match_status=match_status,
            confidence=row_dict["confidence"],
            latency_ms=row_dict["latency_ms"],
            created_at=row_dict["created_at"],
            vendor_tier=row_dict.get("vendor_tier", "STANDARD"),
            requires_human_review=bool(row_dict.get("requires_human_review", False)),
            evidence_contract=evidence_contract,
            clearance_state=row_dict.get("clearance_state", "AUTO_CLEARED")
        ))
    return results

@app.get("/api/evaluation/baseline")
async def get_evaluation_baseline():
    """
    Returns the pre-computed evaluation stats and discrepancy breakdown
    from the latest evaluate.py batch run.
    """
    eval_dir = DB_PATH.parent / "eval_results"
    if not eval_dir.exists():
        raise HTTPException(status_code=404, detail="Run scripts/evaluate.py first (eval_results dir missing)")
        
    results_files = list(eval_dir.glob("*_results.json"))
    if not results_files:
        raise HTTPException(status_code=404, detail="Run scripts/evaluate.py first (no json files found)")
        
    latest_file = max(results_files, key=lambda p: p.stat().st_mtime)
    
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        total_processed = data.get("total_processed", 0)
        correct_count = data.get("correct_count", 0)
        accuracy = data.get("accuracy", 0.0)
        total_batch_time_seconds = data.get("total_batch_time_seconds", 0.0)
        avg_seconds_per_record = data.get("avg_seconds_per_record", 0.0)
        discrepancy_matrix = data.get("discrepancy_matrix", {})
        macro_f1 = data.get("macro_f1", 0.0)
        
        # Build honest exceptions list
        exceptions = []
        for record in data.get("records", []):
            if record.get("actual_status") != "MATCH":
                # Find best reason
                if record.get("system_failure_reason"):
                    reason = record["system_failure_reason"]
                elif record.get("exception_reason"):
                    reason = record["exception_reason"]
                else:
                    reason = ", ".join(record.get("discrepancies", [])) or "Unknown reason"
                    
                exceptions.append({
                    "ledger_id": record.get("ledger_id"),
                    "expected_status": record.get("expected_status"),
                    "actual_status": record.get("actual_status"),
                    "reason": reason,
                    "confidence": record.get("confidence", 0.0)
                })
                
        return {
            "batch_id": data.get("batch_id"),
            "timestamp": data.get("timestamp"),
            "total_processed": total_processed,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "total_batch_time_seconds": total_batch_time_seconds,
            "avg_seconds_per_record": avg_seconds_per_record,
            "discrepancy_matrix": discrepancy_matrix,
            "macro_f1": macro_f1,
            "exceptions": exceptions
        }
    except Exception as e:
        logger.error(f"Failed to read evaluation file: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse evaluation file")


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run_detail(run_id: str, db: sqlite3.Connection = Depends(get_db)):
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Database not found")

    query = """
        SELECT 
            a.run_id, a.ledger_id, a.match_status, a.confidence, a.latency_ms, a.created_at,
            a.discrepancies, a.exception_reason, a.system_failure_reason,
            a.generated_code, a.execution_result,
            a.vendor_tier, a.requires_human_review, a.clearance_state, a.evidence_contract,
            l.vendor_name, l.invoice_number
        FROM audit_log a
        JOIN ledger l ON a.ledger_id = l.ledger_id
        WHERE a.run_id = ?
    """
    row = db.execute(query, (run_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    row_dict = dict(row)
    # Deserialize JSON fields
    try:
        discrepancies = json.loads(row_dict["discrepancies"]) if row_dict["discrepancies"] else []
    except json.JSONDecodeError:
        discrepancies = []

    try:
        execution_result = json.loads(row_dict["execution_result"]) if row_dict["execution_result"] else None
    except json.JSONDecodeError:
        execution_result = None

    try:
        evidence_contract = json.loads(row_dict["evidence_contract"]) if row_dict.get("evidence_contract") else None
    except:
        evidence_contract = None

    match_status = row_dict["match_status"]
    if row_dict.get("requires_human_review"):
        match_status = "PENDING REVIEW"

    return RunDetail(
        run_id=row_dict["run_id"],
        ledger_id=row_dict["ledger_id"],
        vendor_name=row_dict["vendor_name"],
        invoice_number=row_dict["invoice_number"],
        match_status=match_status,
        confidence=row_dict["confidence"],
        latency_ms=row_dict["latency_ms"],
        created_at=row_dict["created_at"],
        discrepancies=discrepancies,
        exception_reason=row_dict["exception_reason"],
        system_failure_reason=row_dict["system_failure_reason"],
        generated_code=row_dict["generated_code"],
        execution_result=execution_result,
        vendor_tier=row_dict.get("vendor_tier", "STANDARD"),
        requires_human_review=bool(row_dict.get("requires_human_review", False)),
        clearance_state=row_dict.get("clearance_state", "AUTO_CLEARED"),
        evidence_contract=evidence_contract
    )


@app.post("/api/reconciliation/{run_id}/clearance")
def update_clearance(run_id: str, payload: ClearancePayload, db: sqlite3.Connection = Depends(get_db)):
    if payload.decision == "approve":
        new_state = "MANUALLY_RELEASED"
    elif payload.decision == "override":
        new_state = "MANUALLY_RELEASED"
    elif payload.decision == "reject":
        new_state = "BLOCKED"
    else:
        raise HTTPException(status_code=400, detail="Invalid decision")
        
    row = db.execute("SELECT evidence_contract FROM audit_log WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
        
    try:
        evidence = json.loads(row["evidence_contract"]) if row["evidence_contract"] else {}
    except Exception:
        evidence = {}
        
    evidence["human_clearance"] = {
        "reviewed_by": payload.reviewed_by,
        "decision": payload.decision,
        "reason": payload.reason,
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    # Guarded UPDATE: only transition from PENDING_HUMAN_AUDIT.
    # Returns 409 if another reviewer already approved/rejected this run,
    # preventing a BLOCKED decision from being silently overwritten (fix 31a).
    result = db.execute(
        """UPDATE audit_log
           SET clearance_state = ?, evidence_contract = ?
           WHERE run_id = ? AND clearance_state = 'PENDING_HUMAN_AUDIT'""",
        (new_state, json.dumps(evidence), run_id),
    )
    if result.rowcount == 0:
        # Either already processed or run_id doesn't exist
        current = db.execute(
            "SELECT clearance_state FROM audit_log WHERE run_id = ?", (run_id,)
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail=(
                f"Clearance conflict: run {run_id} is already in state "
                f"'{current['clearance_state']}' and cannot be overwritten. "
                "A concurrent reviewer may have already processed this record."
            ),
        )
    db.commit()
    return {"status": "success", "clearance_state": new_state, "notes": payload.notes}

@app.get("/api/vendors/{vendor_id}/trust")
def get_vendor_trust(vendor_id: str):
    trust_store = VendorTrustStore()
    trust_data = trust_store.get_vendor_trust(vendor_id)
    trust_data["is_routing_active"] = os.getenv("VENDOR_TRUST_ROUTING", "true").lower() == "true"
    return trust_data

def compute_metrics(db: sqlite3.Connection) -> dict:
    try:
        latest = db.execute("SELECT batch_id FROM audit_log ORDER BY created_at DESC LIMIT 1").fetchone()
        if latest and latest["batch_id"]:
            batch_id = latest["batch_id"]
            query = """
                SELECT match_status, confidence, latency_ms, vendor_tier, clearance_state, evidence_contract
                FROM audit_log
                WHERE batch_id = ?
                ORDER BY created_at DESC
            """
            rows = db.execute(query, (batch_id,)).fetchall()
            window_label = f"batch_{batch_id.split('_')[-1][:8]}"
        else:
            query = """
                SELECT match_status, confidence, latency_ms, vendor_tier, clearance_state, evidence_contract
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT 50
            """
            rows = db.execute(query).fetchall()
            window_label = "last_50"
    except sqlite3.OperationalError:
        return {
            "match_rate": 0,
            "partial_rate": 0,
            "exception_rate": 0,
            "open_exception_rate": 0,
            "human_resolved_rate": 0,
            "self_consistency_rate": 1.0,
            "avg_confidence": 0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "vendor_tier_distribution": {"STANDARD": 0, "ENHANCED": 0, "MANDATORY_AUDIT": 0},
            "records_processed": 0,
            "calibration": {
                "0.0-0.3": {"total": 0, "matches": 0},
                "0.3-0.6": {"total": 0, "matches": 0},
                "0.6-0.9": {"total": 0, "matches": 0},
                "0.9-1.0": {"total": 0, "matches": 0}
            },
            "window": "last_50"
        }

    total = len(rows)
    if total == 0:
        return {
            "match_rate": 0,
            "partial_rate": 0,
            "exception_rate": 0,
            "open_exception_rate": 0,
            "human_resolved_rate": 0,
            "self_consistency_rate": 1.0,
            "avg_confidence": 0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "vendor_tier_distribution": {"STANDARD": 0, "ENHANCED": 0, "MANDATORY_AUDIT": 0},
            "records_processed": 0,
            "calibration": {
                "0.0-0.3": {"total": 0, "matches": 0},
                "0.3-0.6": {"total": 0, "matches": 0},
                "0.6-0.9": {"total": 0, "matches": 0},
                "0.9-1.0": {"total": 0, "matches": 0}
            },
            "window": "last_50"
        }
        
    matches = 0
    partials = 0
    exceptions = 0
    open_exceptions = 0
    human_resolved = 0
    self_consistency_passes = 0
    self_consistency_total = 0
    confidences = []
    calibration = {
        "0.0-0.3": {"total": 0, "matches": 0},
        "0.3-0.6": {"total": 0, "matches": 0},
        "0.6-0.9": {"total": 0, "matches": 0},
        "0.9-1.0": {"total": 0, "matches": 0}
    }
    latencies = []
    tier_dist = {"STANDARD": 0, "ENHANCED": 0, "MANDATORY_AUDIT": 0}

    for r in rows:
        st = r["match_status"]
        try:
            cs = r["clearance_state"]
        except IndexError:
            cs = "AUTO_CLEARED"
            
        if st == "MATCH":
            matches += 1
        elif st == "PARTIAL_MATCH":
            partials += 1
        elif st in ("MISMATCH", "SYSTEM_FAILURE", "NON_DETERMINISTIC_FAILURE", "PENDING_REVIEW"):
            exceptions += 1
            if cs in ("MANUALLY_RELEASED", "BLOCKED"):
                human_resolved += 1
            else:
                open_exceptions += 1
        
        try:
            ev = __import__("json").loads(r["evidence_contract"]) if r.get("evidence_contract") else {}
            if ev.get("self_consistency") is not None:
                self_consistency_total += 1
                if ev["self_consistency"] is True:
                    self_consistency_passes += 1
        except:
            pass
            
        confidences.append(r["confidence"])
        
        c = r["confidence"]
        if c <= 0.3:
            b = "0.0-0.3"
        elif c <= 0.6:
            b = "0.3-0.6"
        elif c <= 0.9:
            b = "0.6-0.9"
        else:
            b = "0.9-1.0"
            
        calibration[b]["total"] += 1
        if st == "MATCH":
            calibration[b]["matches"] += 1
        latencies.append(r["latency_ms"])
        
        try:
            tier = r["vendor_tier"] or "STANDARD"
        except IndexError:
            tier = "STANDARD"
            
        if tier in tier_dist:
            tier_dist[tier] += 1
        else:
            tier_dist["STANDARD"] += 1

    avg_conf = sum(confidences) / total
    
    latencies.sort()
    p50_idx = int(total * 0.50)
    p95_idx = int(total * 0.95)
    
    try:
        total_records = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    except sqlite3.OperationalError:
        total_records = 0

    return {
        "match_rate": matches / total,
        "partial_rate": partials / total,
        "exception_rate": exceptions / total,
        "open_exception_rate": open_exceptions / total,
        "human_resolved_rate": human_resolved / exceptions if exceptions > 0 else 0.0,
        "self_consistency_rate": self_consistency_passes / self_consistency_total if self_consistency_total > 0 else 1.0,
        "avg_confidence": avg_conf,
        "calibration": calibration,
        "p50_latency_ms": latencies[p50_idx],
        "p95_latency_ms": latencies[p95_idx],
        "vendor_tier_distribution": tier_dist,
        "records_processed": total_records,
        "window": window_label
    }

@app.get("/api/metrics/snapshot")
def get_metrics_snapshot(db: sqlite3.Connection = Depends(get_db)):
    if not DB_PATH.exists():
        return {
            "match_rate": 0,
            "partial_rate": 0,
            "exception_rate": 0,
            "avg_confidence": 0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "vendor_tier_distribution": {"STANDARD": 0, "ENHANCED": 0, "MANDATORY_AUDIT": 0},
            "records_processed": 0,
            "calibration": {
                "0.0-0.3": {"total": 0, "matches": 0},
                "0.3-0.6": {"total": 0, "matches": 0},
                "0.6-0.9": {"total": 0, "matches": 0},
                "0.9-1.0": {"total": 0, "matches": 0}
            },
            "window": "last_50"
        }
    return compute_metrics(db)

@app.get("/api/metrics/stream")
async def stream_metrics():
    async def event_generator():
        while True:
            if DB_PATH.exists():
                conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    metrics = compute_metrics(conn)
                    if metrics:
                        yield f"data: {json.dumps(metrics)}\n\n"
                finally:
                    conn.close()
            await asyncio.sleep(2)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ── Serve Frontend ────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

frontend_dist = BASE_DIR / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
            
        return FileResponse(frontend_dist / "index.html")


