"""
Excel Migration Pipeline — Stage 1

Reads Dylan_Portfolio_Tracker.xlsx and imports all sheets into the database.
Preserves historical monthly values and marks them source='excel_migration'.

The migration follows these rules:
1. Parse every sheet in the workbook
2. Identify Dashboard, pie sheets, projection boxes, and Monthly Tracking
3. Extract instruments, positions, historical NAVs
4. Import into DB with source='excel_migration'
5. Run reconciliation: migrated totals must match Excel dashboard within £0.01
"""

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models import (
    Instrument,
    Pie,
    Position,
    Transaction,
    Valuation,
    AuditLog,
)
from app.config import settings


def compute_file_hash(file_path: Path) -> str:
    """SHA-256 hash of a file for deduplication."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def migrate_excel(
    db: Session,
    excel_path: str,
    actor: str = "system",
) -> dict:
    """
    Migrate all data from the Excel workbook into the database.

    Returns a dict with migration summary:
    {
        "instruments": int,
        "pies": int,
        "positions": int,
        "valuations": int,
        "transactions": int,
        "file_hash": str,
        "reconciliation_ok": bool,
        "reconciliation_delta": float,
        "warnings": list[str],
    }
    """
    file_path = Path(excel_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    file_hash = compute_file_hash(file_path)

    # Check for duplicate import
    existing = db.query(AuditLog).filter(
        AuditLog.action == "excel_import",
        AuditLog.source_file_hash == file_hash,
    ).first()
    if existing:
        return {
            "instruments": 0, "pies": 0, "positions": 0,
            "valuations": 0, "transactions": 0,
            "file_hash": file_hash,
            "reconciliation_ok": True,
            "reconciliation_delta": 0.0,
            "warnings": ["File already imported (hash match). Skipping."],
        }

    # Read all sheets
    xl = pd.ExcelFile(file_path)
    sheet_names = xl.sheet_names

    warnings = []
    instruments_count = 0
    pies_count = 0
    positions_count = 0
    valuations_count = 0
    transactions_count = 0

    # ── Step 1: Parse Dashboard for summary NAV ──────────────────────────
    dashboard_df = None
    if "Dashboard" in sheet_names:
        dashboard_df = pd.read_excel(xl, sheet_name="Dashboard", header=None)
        # Expected layout: label in col 0, value in col 1
        # Look for "NAV" or "Total Portfolio Value" row
        dashboard_dict = {}
        for _, row in dashboard_df.iterrows():
            if len(row) >= 2 and pd.notna(row.iloc[0]) and pd.notna(row.iloc[1]):
                key = str(row.iloc[0]).strip()
                val = row.iloc[1]
                if isinstance(val, (int, float)):
                    dashboard_dict[key] = val
        # Extract NAV
        nav_excel = None
        for k in ["NAV", "Total Portfolio Value", "Total Value", "Portfolio Value"]:
            if k in dashboard_dict:
                nav_excel = dashboard_dict[k]
                break

    # ── Step 2: Parse Pie sheets ─────────────────────────────────────────
    pie_sheets = [s for s in sheet_names if s not in ["Dashboard", "Monthly Tracking", "Projections"]]
    for sheet_name in pie_sheets:
        df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
        # Skip empty sheets
        if df.dropna(how="all").empty:
            warnings.append(f"Sheet '{sheet_name}' is empty. Skipping.")
            continue

        # First meaningful row is the pie name
        pie_name = None
        for _, row in df.iterrows():
            if len(row) > 0 and pd.notna(row.iloc[0]):
                pie_name = str(row.iloc[0]).strip()
                break
        if not pie_name:
            warnings.append(f"Could not determine pie name for sheet '{sheet_name}'.")
            continue

        # Create or update pie
        pie = db.query(Pie).filter(Pie.name == pie_name).first()
        if not pie:
            pie = Pie(name=pie_name, target_allocation=100.0, status="active")
            db.add(pie)
            db.flush()
            pies_count += 1

        # Parse holdings from the pie sheet
        # Expected: ticker | name | quantity | price | value | weight %
        holdings = _parse_pie_holdings(df, pie, db)
        positions_count += len(holdings)

    # ── Step 3: Parse Monthly Tracking for historical NAVs ────────────────
    if "Monthly Tracking" in sheet_names:
        monthly_df = pd.read_excel(xl, sheet_name="Monthly Tracking")
        # Expected columns: Date, NAV, and per-pie values
        valuations = _parse_monthly_tracking(monthly_df, db)
        valuations_count += len(valuations)

    # ── Step 4: Reconciliation ───────────────────────────────────────────
    reconciliation_ok = False
    reconciliation_delta = 0.0

    if dashboard_df is not None and nav_excel is not None:
        # Compare with current DB total
        total_nav = _calculate_total_nav(db)
        reconciliation_delta = abs(total_nav - nav_excel)
        reconciliation_ok = reconciliation_delta <= 0.01

        if not reconciliation_ok:
            warnings.append(
                f"Reconciliation failed: Excel NAV={nav_excel:.2f}, "
                f"DB NAV={total_nav:.2f}, delta={reconciliation_delta:.2f}"
            )
        else:
            warnings.append(
                f"Reconciliation OK: Excel NAV={nav_excel:.2f}, "
                f"DB NAV={total_nav:.2f}, delta={reconciliation_delta:.4f}"
            )

    # ── Audit log ────────────────────────────────────────────────────────
    audit = AuditLog(
        timestamp=datetime.now(timezone.utc),
        actor=actor,
        action="excel_import",
        entity="portfolio",
        before=None,
        after={
            "instruments": instruments_count,
            "pies": pies_count,
            "positions": positions_count,
            "valuations": valuations_count,
            "transactions": transactions_count,
            "file_hash": file_hash,
        },
        source_file_hash=file_hash,
    )
    db.add(audit)
    db.commit()

    return {
        "instruments": instruments_count,
        "pies": pies_count,
        "positions": positions_count,
        "valuations": valuations_count,
        "transactions": transactions_count,
        "file_hash": file_hash,
        "reconciliation_ok": reconciliation_ok,
        "reconciliation_delta": reconciliation_delta,
        "warnings": warnings,
    }


def _parse_pie_holdings(
    df: pd.DataFrame,
    pie: Pie,
    db: Session,
) -> list[Position]:
    """
    Parse holdings from a pie sheet.

    Expected layout (flexible):
    Row 1: Pie name
    Row 2: Headers (Ticker | Name | Quantity | Price | Value | Weight)
    Rows 3+: Data
    """
    positions = []

    # Find header row
    header_idx = None
    for i, row in df.iterrows():
        vals = [str(v).strip().lower() for v in row if pd.notna(v)]
        if any(h in " ".join(vals) for h in ["ticker", "name", "quantity", "shares"]):
            header_idx = i
            break

    if header_idx is None:
        return positions

    data_rows = df.iloc[header_idx + 1:]

    for _, row in data_rows.iterrows():
        if row.dropna().empty:
            continue

        # Try to extract ticker
        ticker = None
        for v in row:
            if pd.notna(v) and isinstance(v, str) and len(v.strip()) <= 6:
                ticker = v.strip().upper()
                break

        if not ticker:
            continue

        # Get or create instrument
        inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
        if not inst:
            name = ""
            for v in row:
                if pd.notna(v) and isinstance(v, str) and len(v.strip()) > 6:
                    name = v.strip()
                    break
            inst = Instrument(
                ticker=ticker,
                name=name or ticker,
                listing_currency="GBP",
                asset_class="etf",
            )
            db.add(inst)
            db.flush()
            inst_id = inst.id
        else:
            inst_id = inst.id

        # Get quantity
        quantity = None
        for v in row:
            if pd.notna(v) and isinstance(v, (int, float)):
                quantity = float(v)
                break

        if quantity is None or quantity <= 0:
            continue

        positions.append(Position(
            pie_id=pie.id,
            instrument_id=inst_id,
            quantity=quantity,
        ))

    return positions


def _parse_monthly_tracking(
    df: pd.DataFrame,
    db: Session,
) -> list[Valuation]:
    """
    Parse Monthly Tracking sheet for historical NAV snapshots.

    Expected columns: Date, and optionally per-pie NAV columns.
    """
    valuations = []

    if df.empty or df.columns.empty:
        return valuations

    # First column should be dates
    date_col = df.columns[0]
    date_col = pd.to_datetime(df[date_col], errors="coerce")

    for i, row in df.iterrows():
        if pd.isna(row.iloc[0]):
            continue

        val_date = row.iloc[0]
        if not isinstance(val_date, (pd.Timestamp, date)):
            continue

        if isinstance(val_date, pd.Timestamp):
            val_date = val_date.date()

        # Total NAV (usually first numeric column or a column named "NAV")
        total_nav = None
        for col in df.columns[1:]:
            val = row[col]
            if pd.notna(val) and isinstance(val, (int, float)):
                total_nav = float(val)
                break

        if total_nav is None:
            continue

        valuations.append(Valuation(
            date=val_date,
            portfolio_nav_gbp=total_nav,
            source="excel_migration",
        ))

    return valuations


def _calculate_total_nav(db: Session) -> float:
    """Calculate total portfolio NAV from current positions and prices."""
    total = 0.0
    positions = db.query(Position).all()
    for pos in positions:
        # Get latest price
        price = (
            db.query(Price)
            .filter(Price.instrument_id == pos.instrument_id)
            .order_by(Price.date.desc())
            .first()
        )
        if price and price.close > 0:
            total += pos.quantity * price.close
    return total
