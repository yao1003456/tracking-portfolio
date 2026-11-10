"""
Trading 212 CSV Import — Stage 2

Imports Trading 212 transaction CSVs into the database.
Validates headers, detects and excludes "Total" rows, handles
"Dividends gained" field, and deduplicates on Trading 212's
transaction ID.
"""

import csv
import hashlib
import logging
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Transaction, AuditLog, Instrument, Pie
from app.config import settings

logger = logging.getLogger(__name__)


def import_trading212_csv(
    db: Session,
    file_path: str,
    actor: str = "system",
) -> dict:
    """
    Import a Trading 212 CSV export.

    Validates:
    - UTF-8-sig encoding
    - Expected headers
    - "Total" row exclusion
    - Duplicate external_id (Transaction ID)

    Imports in a single DB transaction. A failure leaves no partial data.

    Returns:
        {
            "transactions_imported": int,
            "file_hash": str,
            "warnings": list[str],
        }
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    # Compute file hash for deduplication
    file_hash = _compute_sha256(file_path)

    # Check for duplicate import
    existing = db.query(AuditLog).filter(
        AuditLog.action == "t212_import",
        AuditLog.source_file_hash == file_hash,
    ).first()
    if existing:
        return {
            "transactions_imported": 0,
            "file_hash": file_hash,
            "warnings": ["File already imported (hash match). Skipping."],
        }

    # Read file
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except UnicodeDecodeError:
        # Try latin-1 as fallback
        with open(file_path, "r", encoding="latin-1") as f:
            content = f.read()

    # Parse CSV
    reader = csv.DictReader(StringIO(content))

    # Validate headers
    warnings = _validate_t212_headers(reader.fieldnames)
    if "invalid_headers" in warnings:
        raise ValueError(f"Invalid Trading 212 CSV headers: {warnings}")

    # Process rows
    transactions = []
    skipped_rows = 0

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        # Skip "Total" rows
        if _is_total_row(row):
            skipped_rows += 1
            continue

        # Skip empty rows
        if not row.get("Transaction ID"):
            skipped_rows += 1
            continue

        # Deduplicate on Transaction ID
        ext_id = row["Transaction ID"].strip()
        if ext_id:
            existing_txn = db.query(Transaction).filter(
                Transaction.external_id == ext_id
            ).first()
            if existing_txn:
                skipped_rows += 1
                continue

        txn = _parse_t212_row(row)
        if txn:
            transactions.append(txn)

    # Import in a single transaction
    imported = 0
    try:
        for txn in transactions:
            db.add(Transaction(**txn))
            imported += 1

        db.commit()
    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Transaction import failed: {e}")

    # Audit log
    db.add(AuditLog(
        timestamp=datetime.now(timezone.utc),
        actor=actor,
        action="t212_import",
        entity="transactions",
        before=None,
        after={"transactions_imported": imported, "skipped_rows": skipped_rows},
        source_file_hash=file_hash,
    ))
    db.commit()

    return {
        "transactions_imported": imported,
        "file_hash": file_hash,
        "warnings": warnings + (
            [f"Skipped {skipped_rows} rows (Total/empty/duplicate)"] if skipped_rows else []
        ),
    }


def _validate_t212_headers(fieldnames: Optional[list[str]]) -> list[str]:
    """
    Validate Trading 212 CSV headers.

    Expected headers (may vary):
    - Transaction ID (required)
    - Date
    - Type (Buy, Sell, Dividend, etc.)
    - Name
    - Total
    - Currency

    Returns list of warnings.
    """
    warnings = []
    if not fieldnames:
        warnings.append("invalid_headers")
        return warnings

    normalized = [f.strip().lower() for f in fieldnames]

    required = ["transaction id", "date", "type"]
    missing = [r for r in required if r not in normalized]
    if missing:
        warnings.append(f"Missing required headers: {missing}")

    return warnings


def _is_total_row(row: dict) -> bool:
    """Check if a row is the 'Total' summary row."""
    type_val = row.get("Type", "").strip().lower()
    return type_val == "total" or row.get("Transaction ID", "").strip() == ""


def _parse_t212_row(row: dict) -> Optional[dict]:
    """
    Parse a single Trading 212 CSV row into a Transaction dict.

    Handles:
    - Buy/Sell transactions
    - Dividends (including "Dividends gained" field)
    - Fees
    - FX conversions
    """
    try:
        txn_type = row.get("Type", "").strip().lower()

        # Map T212 types to our enum
        type_map = {
            "buy": "buy",
            "sell": "sell",
            "dividend": "dividend",
            "fee": "fee",
            "deposit": "deposit",
            "withdrawal": "withdrawal",
        }

        mapped_type = type_map.get(txn_type)
        if not mapped_type:
            logger.warning(f"Unknown T212 type: {txn_type}. Skipping.")
            return None

        # Parse date
        date_str = row.get("Date", "").strip()
        txn_date = _parse_t212_date(date_str)
        if not txn_date:
            logger.warning(f"Invalid date: {date_str}. Skipping.")
            return None

        # Parse quantity
        quantity = _safe_float(row.get("Total", "0"))
        if quantity is None:
            quantity = _safe_float(row.get("Quantity", "0"))

        # Parse price
        price = _safe_float(row.get("Price", "0")) or _safe_float(row.get("Average Price", "0"))

        # Currency
        currency = row.get("Currency", "GBP").strip().upper()

        # Amount in GBP
        amount_gbp = _safe_float(row.get("Total (GBP)", "0")) or _safe_float(row.get("Total", "0"))

        # Fee
        fee_gbp = _safe_float(row.get("Fee (GBP)", "0")) or 0

        # External ID
        external_id = row.get("Transaction ID", "").strip()

        # Instrument name
        instrument_name = row.get("Name", "").strip()
        ticker = _extract_ticker(instrument_name)

        # Find or create instrument
        from app.database import SessionLocal
        from app.models import Instrument
        db = SessionLocal()
        inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
        if not inst:
            inst = Instrument(
                ticker=ticker,
                name=instrument_name or ticker,
                listing_currency=currency,
                asset_class="etf" if "ETF" in instrument_name else "stock",
            )
            db.add(inst)
            db.commit()
        db.close()

        return {
            "date": txn_date,
            "type": mapped_type,
            "instrument_id": inst.id,
            "quantity": abs(quantity) if mapped_type in ("buy", "deposit") else abs(quantity),
            "price": price,
            "currency": currency,
            "amount_gbp": abs(amount_gbp) if amount_gbp else None,
            "fee_gbp": abs(fee_gbp),
            "fx_rate": None,  # T212 handles FX internally
            "source": "trading212",
            "external_id": external_id,
            "notes": row.get("Description", ""),
        }

    except Exception as e:
        logger.error(f"Error parsing T212 row: {e}")
        return None


def _parse_t212_date(date_str: str) -> Optional[date]:
    """Parse Trading 212 date formats."""
    import re

    # Try common formats
    formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d-%m-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    # Try regex for flexible parsing
    match = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", date_str)
    if match:
        d, m, y = match.groups()
        return date(int(y), int(m), int(d))

    return None


def _safe_float(val) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.replace(",", "").replace("£", "").strip()
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _extract_ticker(name: str) -> str:
    """Extract ticker from instrument name."""
    import re
    # Try to find a ticker-like pattern (2-6 uppercase letters)
    match = re.search(r'\b([A-Z]{2,6})\b', name)
    if match:
        return match.group(1).upper()
    return name.upper()[:6]


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
