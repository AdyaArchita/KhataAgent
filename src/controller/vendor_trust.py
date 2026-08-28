import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = _DATA_DIR / "synthetic_ledger.db"

class VendorTrustStore:
    def __init__(self, db_path: Path | str = _DB_PATH):
        self.db_path = str(db_path)
        self.init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Create the vendor trust tables if they do not exist."""
        with closing(self._get_conn()) as conn:
            with conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS vendor_trust_scores (
                    vendor_id TEXT PRIMARY KEY,
                    vendor_name TEXT NOT NULL,
                    score REAL DEFAULT 100.0,
                    tier TEXT DEFAULT 'STANDARD',
                    updated_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS vendor_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id TEXT NOT NULL,
                    invoice_id TEXT NOT NULL,
                    exception_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    ts TIMESTAMP NOT NULL
                );
            """)

    def _update_tier_and_get(self, conn: sqlite3.Connection, vendor_id: str) -> str:
        """Recalculate tier based on score and rolling 90-day incidents."""
        # Get current score
        row = conn.execute(
            "SELECT score FROM vendor_trust_scores WHERE vendor_id = ?", 
            (vendor_id,)
        ).fetchone()
        if not row:
            return "STANDARD"
        
        score = row["score"]

        # Check incidents in last 90 days
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        incident_count = conn.execute(
            "SELECT COUNT(*) as count FROM vendor_incidents WHERE vendor_id = ? AND ts >= ?",
            (vendor_id, cutoff)
        ).fetchone()["count"]

        # Determine tier
        if incident_count >= 3 or score < 70:
            tier = "MANDATORY_AUDIT"
        elif score < 90:
            tier = "ENHANCED"
        else:
            tier = "STANDARD"

        conn.execute(
            "UPDATE vendor_trust_scores SET tier = ?, updated_at = ? WHERE vendor_id = ?",
            (tier, datetime.now(UTC).isoformat(), vendor_id)
        )
        return tier

    def record_exception(
        self, 
        vendor_id: str, 
        vendor_name: str, 
        invoice_id: str, 
        exception_type: str, 
        severity: str = "HIGH",
        penalty: float = 15.0
    ) -> None:
        """Record an exception and penalize the vendor's score."""
        with closing(self._get_conn()) as conn:
            with conn:
                # Ensure vendor exists
                conn.execute("""
                INSERT INTO vendor_trust_scores (vendor_id, vendor_name, score, updated_at)
                VALUES (?, ?, 100.0, ?)
                ON CONFLICT(vendor_id) DO NOTHING
            """, (vendor_id, vendor_name, datetime.now(UTC).isoformat()))

            # Record incident
            conn.execute("""
                INSERT INTO vendor_incidents (vendor_id, invoice_id, exception_type, severity, ts)
                VALUES (?, ?, ?, ?, ?)
            """, (vendor_id, invoice_id, exception_type, severity, datetime.now(UTC).isoformat()))

            # Penalize score
            conn.execute("""
                UPDATE vendor_trust_scores 
                SET score = MAX(0.0, score - ?), updated_at = ? 
                WHERE vendor_id = ?
            """, (penalty, datetime.now(UTC).isoformat(), vendor_id))

            self._update_tier_and_get(conn, vendor_id)

    def record_clean_match(self, vendor_id: str, vendor_name: str, recovery: float = 5.0) -> None:
        """Record a clean match and slightly recover the vendor's score."""
        with closing(self._get_conn()) as conn:
            with conn:
                # Ensure vendor exists
                conn.execute("""
                INSERT INTO vendor_trust_scores (vendor_id, vendor_name, score, updated_at)
                VALUES (?, ?, 100.0, ?)
                ON CONFLICT(vendor_id) DO NOTHING
            """, (vendor_id, vendor_name, datetime.now(UTC).isoformat()))

            # Recover score
            conn.execute("""
                UPDATE vendor_trust_scores 
                SET score = MIN(100.0, score + ?), updated_at = ? 
                WHERE vendor_id = ?
            """, (recovery, datetime.now(UTC).isoformat(), vendor_id))

            self._update_tier_and_get(conn, vendor_id)

    def get_tier(self, vendor_id: str) -> str:
        """Get the current tier for a vendor, recalculating it if needed."""
        with closing(self._get_conn()) as conn:
            with conn:
                return self._update_tier_and_get(conn, vendor_id)

    def get_vendor_trust(self, vendor_id: str) -> dict[str, Any]:
        """Fetch the vendor's score, tier, and incident history."""
        with closing(self._get_conn()) as conn:
            score_row = conn.execute(
                "SELECT vendor_name, score, tier, updated_at FROM vendor_trust_scores WHERE vendor_id = ?",
                (vendor_id,)
            ).fetchone()

            if not score_row:
                return {
                    "vendor_id": vendor_id,
                    "vendor_name": vendor_id,
                    "score": 100.0,
                    "tier": "STANDARD",
                    "incidents": []
                }

            incidents = conn.execute(
                "SELECT id, invoice_id, exception_type, severity, ts FROM vendor_incidents WHERE vendor_id = ? ORDER BY ts DESC",
                (vendor_id,)
            ).fetchall()

            return {
                "vendor_id": vendor_id,
                "vendor_name": score_row["vendor_name"],
                "score": score_row["score"],
                "tier": score_row["tier"],
                "updated_at": score_row["updated_at"],
                "incidents": [dict(i) for i in incidents]
            }
