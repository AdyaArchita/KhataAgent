#!/usr/bin/env python3
"""Synthetic dataset generator for KhataAgent reconciliation engine.

Generates reproducible test data (seed = 42, 80 records) distributed as:
  ~65 %  (52 records)  clean matches
  ~25 %  (20 records)  clear discrepancies
  ~10 %  ( 8 records)  ambiguous partial cases

Outputs
───────
  data/synthetic_ledger.db         SQLite with ``ledger`` + ``audit_log`` tables
  data/raw_invoices/{ledger_id}.txt   unstructured invoice text per record
  data/manifest.json               seed, counts, checksums
  data/chroma/                     ChromaDB collection  (only with --with-embeddings)

Ledger schema mirrors ``controller.state.TransactionData`` 1-to-1
(see constraint 9).

Usage
─────
  uv run python scripts/generate_dataset.py
  uv run python scripts/generate_dataset.py --with-embeddings

Note:  Structured data (ledger + invoices) is fully reproducible from
the fixed seed.  Chroma embeddings require a live OpenAI API call
(OPENAI_API_KEY in ``.env``) and are therefore opt-in via the flag.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ── constants ────────────────────────────────────────────────────────

SEED = 42
TOTAL_RECORDS = 80
CLEAN_COUNT = 52       # indices 0–51
DISCREPANCY_COUNT = 20  # indices 52–71
PARTIAL_COUNT = 8       # indices 72–79

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "synthetic_ledger.db"
INVOICES_DIR = DATA_DIR / "raw_invoices"
MANIFEST_PATH = DATA_DIR / "manifest.json"
CHROMA_DIR = DATA_DIR / "chroma"

# ── realistic Indian B2B vendor data ─────────────────────────────────

VENDORS: list[dict[str, str]] = [
    {"name": "Tata Steel Ltd", "gstin": "27AAACT2727Q1ZV"},
    {"name": "Infosys Limited", "gstin": "29AABCI5678A1Z5"},
    {"name": "Reliance Industries Ltd", "gstin": "27AABCR9012P1Z1"},
    {"name": "Wipro Technologies Pvt Ltd", "gstin": "29AABCW3456D1Z8"},
    {"name": "HCL Technologies Ltd", "gstin": "09AABCH7890K1Z3"},
    {"name": "Larsen & Toubro Ltd", "gstin": "27AABCL2345M1Z2"},
    {"name": "Mahindra & Mahindra Ltd", "gstin": "27AABCM6789N1Z7"},
    {"name": "Bajaj Auto Ltd", "gstin": "27AABCB0123P1Z4"},
    {"name": "Sun Pharma Industries Ltd", "gstin": "24AABCS4567Q1Z6"},
    {"name": "Asian Paints Ltd", "gstin": "27AABCA8901R1Z9"},
    {"name": "Hindustan Unilever Ltd", "gstin": "27AABCH2345S1Z5"},
    {"name": "ITC Limited", "gstin": "19AABCI6789T1Z2"},
    {"name": "Bharti Airtel Ltd", "gstin": "07AABCB0123U1Z8"},
    {"name": "Tech Mahindra Ltd", "gstin": "27AABCT4567V1Z1"},
    {"name": "Godrej Industries Ltd", "gstin": "27AABCG8901W1Z6"},
]

PRODUCTS: list[tuple[str, float]] = [
    ("Steel Plates (Grade A)", 450.00),
    ("IT Consulting Services", 2500.00),
    ("Enterprise Software License", 15000.00),
    ("Office Stationery Kit", 125.00),
    ("Server Maintenance Contract", 8000.00),
    ("Cloud Hosting (Monthly)", 12000.00),
    ("Industrial Chemicals - Batch", 3200.00),
    ("Corrugated Packaging Material", 85.50),
    ("Freight & Logistics", 4500.00),
    ("Quality Assurance Testing", 6000.00),
    ("Electrical Components Set", 750.00),
    ("Industrial Lubricants", 1200.00),
    ("Safety Equipment Kit", 2800.00),
    ("Commercial Printing Services", 950.00),
    ("Corporate Catering Services", 350.00),
    ("Hydraulic Press Parts", 5600.00),
    ("Network Cabling Services", 3800.00),
    ("Industrial Paint Supplies", 2100.00),
    ("Precision Bearings Set", 1650.00),
    ("Fire Safety Equipment", 4200.00),
]

# Weighted toward 18 % (most common Indian GST slab for B2B services)
TAX_RATES: list[float] = [0.05, 0.12, 0.18, 0.28]
TAX_RATE_WEIGHTS: list[float] = [0.10, 0.15, 0.60, 0.15]

BUYER_NAME = "KhataAgent Financial Services Pvt Ltd"
BUYER_GSTIN = "07AABCK9876P1ZP"


# ── helpers ──────────────────────────────────────────────────────────

def _make_ledger_id(index: int) -> str:
    """Deterministic UUID from seed + index (UUID-5, DNS namespace)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"khata-{SEED}-{index}"))


def _generate_ledger_record(rng: random.Random, index: int) -> dict:
    """Build one ledger row with realistic Indian B2B invoice data.

    Column names intentionally mirror ``TransactionData`` fields in
    ``src/controller/state.py`` (constraint 9).
    """
    vendor = rng.choice(VENDORS)
    num_items = rng.randint(1, 5)
    selected = rng.sample(PRODUCTS, min(num_items, len(PRODUCTS)))

    line_items: list[dict] = []
    for product_name, base_price in selected:
        quantity = rng.randint(1, 100)
        unit_price = round(base_price * rng.uniform(0.90, 1.10), 2)
        amount = round(quantity * unit_price, 2)
        line_items.append(
            {
                "description": product_name,
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount,
            }
        )

    subtotal = round(sum(it["amount"] for it in line_items), 2)
    tax_rate = rng.choices(TAX_RATES, weights=TAX_RATE_WEIGHTS, k=1)[0]
    tax_amount = round(subtotal * tax_rate, 2)
    total_amount = round(subtotal + tax_amount, 2)

    base_date = datetime(2024, 1, 1, tzinfo=UTC)
    invoice_date = base_date + timedelta(days=rng.randint(0, 730))

    return {
        "ledger_id": _make_ledger_id(index),
        "vendor_name": vendor["name"],
        "invoice_number": f"INV-{invoice_date.year}-{index:04d}",
        "amount": total_amount,
        "tax_amount": tax_amount,
        "tax_rate": tax_rate,
        "gstin": vendor["gstin"],
        "currency": "INR",
        "line_items": json.dumps(line_items),
        "invoice_date": invoice_date.strftime("%Y-%m-%d"),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _render_invoice_text(
    record: dict,
    variation: str,
    rng: random.Random,
) -> tuple[str, str]:
    """Render an unstructured Indian tax invoice from a ledger record.

    ``variation`` controls whether the invoice faithfully reproduces the
    ledger ("clean"), introduces a clear error ("discrepancy"), or a
    small amount drift ("partial").

    Returns the invoice text only — the caller decides where to save it.
    """
    line_items: list[dict] = json.loads(record["line_items"])
    vendor_name: str = record["vendor_name"]
    gstin: str = record["gstin"]
    invoice_number: str = record["invoice_number"]
    invoice_date: str = record["invoice_date"]
    tax_rate: float = record["tax_rate"]
    currency: str = record["currency"]

    # ── apply mutation ───────────────────────────────────────────────
    disc_type = None
    if variation == "discrepancy":
        disc_type = rng.choice(
            ["amount", "tax", "gstin", "missing_line", "currency", "duplicate_line"]
        )

        if disc_type == "amount" and line_items:
            idx = rng.randint(0, len(line_items) - 1)
            offset = rng.uniform(5.0, 500.0) * rng.choice([1, -1])
            line_items[idx]["amount"] = round(line_items[idx]["amount"] + offset, 2)
            line_items[idx]["unit_price"] = round(
                line_items[idx]["amount"] / max(line_items[idx]["quantity"], 1), 2
            )

        elif disc_type == "tax":
            others = [r for r in TAX_RATES if r != tax_rate]
            tax_rate = rng.choice(others)

        elif disc_type == "gstin":
            chars = list(gstin)
            pos = rng.randint(2, len(chars) - 2)
            charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            available_chars = [c for c in charset if c != chars[pos]]
            chars[pos] = rng.choice(available_chars)
            gstin = "".join(chars)

        elif disc_type == "missing_line" and len(line_items) > 1:
            line_items.pop(rng.randint(0, len(line_items) - 1))

        elif disc_type == "currency":
            currency = rng.choice(["USD", "EUR", "GBP"])

        elif disc_type == "duplicate_line" and line_items:
            line_items.append(line_items[rng.randint(0, len(line_items) - 1)].copy())

    elif variation == "partial" and line_items:
        idx = rng.randint(0, len(line_items) - 1)
        offset = rng.uniform(0.02, 1.00) * rng.choice([1, -1])
        line_items[idx]["amount"] = round(line_items[idx]["amount"] + offset, 2)

    # ── recalculate totals ───────────────────────────────────────────
    subtotal = round(sum(it["amount"] for it in line_items), 2)
    calc_tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + calc_tax, 2)

    # ── format tax lines ─────────────────────────────────────────────
    if tax_rate in (0.05, 0.12):
        tax_display = f"IGST ({tax_rate * 100:.0f}%): ₹{calc_tax:,.2f}"
    else:
        half = round(calc_tax / 2, 2)
        pct = tax_rate * 50
        tax_display = (
            f"CGST ({pct:.0f}%): ₹{half:,.2f}\n"
            f"SGST ({pct:.0f}%): ₹{half:,.2f}"
        )

    # ── line items block ─────────────────────────────────────────────
    items_block = "\n".join(
        f"{i}. {it['description']} - "
        f"Qty: {it['quantity']} x ₹{it['unit_price']:,.2f} = "
        f"₹{it['amount']:,.2f}"
        for i, it in enumerate(line_items, 1)
    )

    acct_suffix = rng.randint(1000, 9999)
    ifsc_suffix = rng.randint(1000, 9999)

    text = (
        "TAX INVOICE\n"
        "══════════════════════════════════════════\n"
        f"Vendor: {vendor_name}\n"
        f"GSTIN: {gstin}\n"
        f"Invoice No: {invoice_number}\n"
        f"Date: {invoice_date}\n"
        "\n"
        f"Bill To: {BUYER_NAME}\n"
        f"GSTIN: {BUYER_GSTIN}\n"
        "\n"
        "────────────────────────────────────────\n"
        "ITEMS:\n"
        f"{items_block}\n"
        "\n"
        "────────────────────────────────────────\n"
        f"Subtotal: ₹{subtotal:,.2f}\n"
        f"{tax_display}\n"
        f"Total Tax: ₹{calc_tax:,.2f}\n"
        "\n"
        f"TOTAL: ₹{total:,.2f}\n"
        f"Currency: {currency}\n"
        "\n"
        "Payment Terms: Net 30\n"
        "Bank: State Bank of India\n"
        f"Account: XXXX-XXXX-{acct_suffix}\n"
        f"IFSC: SBIN000{ifsc_suffix}\n"
        "══════════════════════════════════════════\n"
    )
    return text, disc_type


# ── SQLite schema ────────────────────────────────────────────────────

_LEDGER_DDL = """\
CREATE TABLE IF NOT EXISTS ledger (
    ledger_id       TEXT PRIMARY KEY,
    vendor_name     TEXT NOT NULL,
    invoice_number  TEXT NOT NULL,
    amount          REAL NOT NULL,
    tax_amount      REAL NOT NULL,
    tax_rate        REAL NOT NULL,
    gstin           TEXT NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'INR',
    line_items      TEXT NOT NULL,          -- JSON array
    invoice_date    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expected_status TEXT,
    expected_discrepancy_type TEXT
);
"""

_AUDIT_DDL = """\
CREATE TABLE IF NOT EXISTS audit_log (
    run_id                TEXT PRIMARY KEY,
    ledger_id             TEXT NOT NULL,
    match_status          TEXT NOT NULL,
    confidence            REAL NOT NULL,
    discrepancies         TEXT,              -- JSON array
    exception_reason      TEXT,
    system_failure_reason TEXT,
    generated_code        TEXT,
    execution_result      TEXT,              -- JSON object
    token_usage           TEXT,              -- JSON object
    latency_ms            REAL NOT NULL DEFAULT 0.0,
    created_at            TEXT NOT NULL
);
"""

_RAZORPAY_DDL = """\
CREATE TABLE IF NOT EXISTS razorpay_settlements (
    settlement_id TEXT PRIMARY KEY,
    invoice_id TEXT UNIQUE,
    settlement_status TEXT,
    amount_settled REAL,
    gateway_fee REAL,
    processed_at TEXT
);
"""


# ── main generation logic ────────────────────────────────────────────

def generate(*, with_embeddings: bool = False) -> None:
    """Generate the full synthetic dataset."""
    rng = random.Random(SEED)

    # ── prepare directories ──────────────────────────────────────────
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if INVOICES_DIR.exists():
        shutil.rmtree(INVOICES_DIR)
    INVOICES_DIR.mkdir(parents=True)

    # ── create / reset SQLite ────────────────────────────────────────
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.executescript(_LEDGER_DDL)
    cur.executescript(_AUDIT_DDL)
    cur.executescript(_RAZORPAY_DDL)

    # ── generate records ─────────────────────────────────────────────
    all_records: list[dict] = []
    all_invoices: list[tuple[str, str]] = []  # (ledger_id, text)

    for idx in range(TOTAL_RECORDS):
        record = _generate_ledger_record(rng, idx)

        # Decide variation based on index ranges
        if idx < CLEAN_COUNT:
            variation = "clean"
        elif idx < CLEAN_COUNT + DISCREPANCY_COUNT:
            variation = "discrepancy"
        else:
            variation = "partial"

        invoice_text, disc_type = _render_invoice_text(record, variation, rng)
        
        expected_status = "MATCH"
        expected_discrepancy_type = None
        
        if variation == "discrepancy":
            expected_status = "MISMATCH"
            map_disc = {
                "amount": "AMOUNT_MISMATCH",
                "tax": "TAX_MISMATCH",
                "gstin": "GSTIN_MISMATCH",
                "missing_line": "AMOUNT_MISMATCH",
                "currency": "CURRENCY_MISMATCH",
                "duplicate_line": "AMOUNT_MISMATCH"
            }
            expected_discrepancy_type = map_disc.get(disc_type)
        elif variation == "partial":
            expected_status = "PARTIAL_MATCH"
            expected_discrepancy_type = "AMOUNT_MISMATCH"

        # Insert ledger row (always uses the *original* record data)
        cur.execute(
            "INSERT INTO ledger "
            "(ledger_id, vendor_name, invoice_number, amount, tax_amount, "
            " tax_rate, gstin, currency, line_items, invoice_date, created_at, expected_status, expected_discrepancy_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record["ledger_id"],
                record["vendor_name"],
                record["invoice_number"],
                record["amount"],
                record["tax_amount"],
                record["tax_rate"],
                record["gstin"],
                record["currency"],
                record["line_items"],
                record["invoice_date"],
                record["created_at"],
                expected_status,
                expected_discrepancy_type
            ),
        )

        gateway_fee = round(record["amount"] * 0.02, 2)
        if rng.random() < 0.05:
            amount_settled = round(record["amount"] - gateway_fee - rng.uniform(10, 500), 2)
        else:
            amount_settled = round(record["amount"] - gateway_fee, 2)
        
        cur.execute(
            "INSERT INTO razorpay_settlements "
            "(settlement_id, invoice_id, settlement_status, amount_settled, gateway_fee, processed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                record["ledger_id"],
                "SETTLED",
                amount_settled,
                gateway_fee,
                datetime.now(UTC).isoformat()
            )
        )

        # Write invoice file
        invoice_path = INVOICES_DIR / f"{record['ledger_id']}.txt"
        invoice_path.write_text(invoice_text, encoding="utf-8")

        all_records.append(record)
        all_invoices.append((record["ledger_id"], invoice_text))

    conn.commit()
    conn.close()

    # ── write manifest ───────────────────────────────────────────────
    manifest = {
        "seed": SEED,
        "total": TOTAL_RECORDS,
        "clean": CLEAN_COUNT,
        "discrepancy": DISCREPANCY_COUNT,
        "partial": PARTIAL_COUNT,
        "db_path": str(DB_PATH),
        "invoices_dir": str(INVOICES_DIR),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[OK] Manifest written to {MANIFEST_PATH}")
    print(f"[OK] Ledger:  {TOTAL_RECORDS} rows in {DB_PATH}")
    print(f"[OK] Invoices: {TOTAL_RECORDS} files in {INVOICES_DIR}")

    # ── optional: embed into ChromaDB ────────────────────────────────
    if with_embeddings:
        _embed_invoices(all_invoices)
    else:
        print(
            "[INFO] Skipping Chroma embeddings (pass --with-embeddings to enable). "
            "Structured data is fully reproducible without API calls."
        )


def _embed_invoices(invoices: list[tuple[str, str]]) -> None:
    """Embed invoice texts into a local ChromaDB collection.

    Requires ``OPENAI_API_KEY`` in the environment / ``.env`` file and
    a network call to OpenAI — this is intentionally opt-in.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[WARN] OPENAI_API_KEY not found -- skipping Chroma embeddings.")
        return

    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    # Clean previous Chroma data for idempotency
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    embedding_fn = OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name="text-embedding-3-small",
    )
    collection = client.get_or_create_collection(
        name="invoices",
        embedding_function=embedding_fn,  # type: ignore[arg-type]
    )

    # Batch-add in chunks of 20 to stay within rate limits
    batch_size = 20
    for start in range(0, len(invoices), batch_size):
        batch = invoices[start : start + batch_size]
        collection.add(
            ids=[lid for lid, _ in batch],
            documents=[text for _, text in batch],
            metadatas=[{"ledger_id": lid} for lid, _ in batch],
        )

    print(f"[OK] Chroma: {len(invoices)} documents embedded in {CHROMA_DIR}")


# ── CLI entry point ──────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic reconciliation dataset for KhataAgent."
    )
    parser.add_argument(
        "--with-embeddings",
        action="store_true",
        default=False,
        help=(
            "Embed invoice texts into ChromaDB using text-embedding-3-small. "
            "Requires OPENAI_API_KEY. Without this flag, the structured "
            "ledger + invoice files are generated fully offline."
        ),
    )
    args = parser.parse_args()
    generate(with_embeddings=args.with_embeddings)


if __name__ == "__main__":
    main()
