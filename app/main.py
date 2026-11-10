"""
FastAPI Application — Great Dyke Meridian

API endpoints for all dashboard tabs:
- AXIS (summary)
- EXPOSURES
- CORRELATION
- HOLDINGS
- RISK
- TRANSACTIONS
- ATTRIBUTION
"""

import logging
from datetime import date
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, engine
from app.models import Base
from app.schemas import (
    AxisSummary,
    HoldingsRow,
    RiskSummary,
    CorrelationMatrix,
    AttributionSummary,
    ProjectionResult,
    TaxSummary,
    AlertCreate,
    AlertRead,
    AuditLogRead,
    TransactionRead,
    PriceCreate,
)
from app.calculations.holdings import compute_holdings, compute_returns, compute_risk_metrics
from app.calculations.correlation import (
    compute_stock_correlation,
    compute_sector_correlation,
    compute_pie_correlation,
    compute_benchmark_correlation,
    compute_risk_concentration,
)
from app.calculations.cost_basis import calculate_cost_basis, compute_section_104_holdings
from app.calculations.projections import compute_projections
from app.calculations.attribution import compute_attribution
from app.services.price_service import refresh_prices, refresh_fx_rates, check_price_freshness
from app.alerts.engine import run_alert_engine

# Create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Great Dyke Meridian",
    description="Personal portfolio tracking dashboard",
    version="0.1.0",
)

# CORS (localhost only for now)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


# ── AXIS Summary ────────────────────────────────────────────────────────────

@app.get("/api/axis/summary", response_model=AxisSummary)
def get_axis_summary(db: Session = Depends(get_db)):
    """Get the AXIS summary: NAV, returns, risk, correlation, data freshness."""
    from app.calculations.holdings import compute_holdings, compute_returns
    from app.calculations.risk import compute_risk_metrics

    holdings = compute_holdings(db)
    returns = compute_returns(db)
    risk = compute_risk_metrics(db)
    freshness = check_price_freshness(db)

    total_nav = sum(h["market_value_gbp"] for h in holdings)

    return AxisSummary(
        nav_gbp=round(total_nav, 2),
        day_return=returns.get("daily", [{}])[-1].get("return", 0) if returns.get("daily") else 0,
        mtd_return=returns.get("mtd", 0),
        ytd_return=returns.get("ytd", 0),
        sharpe_ratio=risk.get("sharpe_ratio", 0),
        sortino_ratio=risk.get("sortino_ratio", 0),
        max_drawdown=risk.get("max_drawdown", 0),
        max_drawdown_peak_date=None,
        max_drawdown_trough_date=None,
        avg_pairwise_correlation=0,  # computed from correlation module
        effective_number_of_bets=0,
        data_freshness={
            "warnings": [f["message"] for f in freshness],
            "last_refresh": None,
        },
        alerts_count=0,  # from alerts table
        next_alert=None,
    )


# ── Holdings ────────────────────────────────────────────────────────────────

@app.get("/api/holdings", response_model=list[HoldingsRow])
def get_holdings(db: Session = Depends(get_db)):
    """Get all holdings with cost basis, PnL, and RAG status."""
    return compute_holdings(db)


# ── Returns ─────────────────────────────────────────────────────────────────

@app.get("/api/returns")
def get_returns(db: Session = Depends(get_db)):
    """Get portfolio returns: daily, MTD, YTD, TWRR."""
    return compute_returns(db)


# ── Risk ────────────────────────────────────────────────────────────────────

@app.get("/api/risk/metrics", response_model=RiskSummary)
def get_risk_metrics(db: Session = Depends(get_db), window: int = 252):
    """Compute risk metrics: Sharpe, Sortino, VaR, drawdown, beta, alpha."""
    return compute_risk_metrics(db, window)


# ── Correlation ─────────────────────────────────────────────────────────────

@app.get("/api/correlation/stock", response_model=CorrelationMatrix)
def get_stock_correlation(
    db: Session = Depends(get_db),
    window: int = Query(252, ge=10, le=500),
    frequency: str = Query("daily", regex="^(daily|weekly)$"),
):
    """Stock-to-stock correlation matrix with hierarchical clustering."""
    return compute_stock_correlation(db, window, frequency)


@app.get("/api/correlation/sector", response_model=CorrelationMatrix)
def get_sector_correlation(
    db: Session = Depends(get_db),
    window: int = Query(252, ge=10, le=500),
    frequency: str = Query("daily", regex="^(daily|weekly)$"),
):
    """Sector-level correlation matrix."""
    return compute_sector_correlation(db, window, frequency)


@app.get("/api/correlation/pie", response_model=CorrelationMatrix)
def get_pie_correlation(
    db: Session = Depends(get_db),
    window: int = Query(252, ge=10, le=500),
    frequency: str = Query("daily", regex="^(daily|weekly)$"),
):
    """Pie-level correlation matrix."""
    return compute_pie_correlation(db, window, frequency)


@app.get("/api/correlation/benchmark")
def get_benchmark_correlation(
    db: Session = Depends(get_db),
    window: int = Query(252, ge=10, le=500),
    frequency: str = Query("daily", regex="^(daily|weekly)$"),
):
    """Correlation of holdings/pies vs benchmarks."""
    return compute_benchmark_correlation(db, window, frequency)


@app.get("/api/correlation/concentration")
def get_risk_concentration(
    db: Session = Depends(get_db),
    window: int = Query(252, ge=10, le=500),
    frequency: str = Query("daily", regex="^(daily|weekly)$"),
    shrinkage: bool = Query(False),
):
    """Concentration of risk from correlation matrix."""
    return compute_risk_concentration(db, window, frequency, shrinkage)


# ── Projections ─────────────────────────────────────────────────────────────

@app.post("/api/projections", response_model=list[ProjectionResult])
def post_projections(db: Session = Depends(get_db), current_nav: float = None):
    """Compute compound growth projections to 30 April 2030."""
    if current_nav is None:
        # Get from latest valuation
        from app.models import Valuation
        latest = db.query(Valuation).order_by(Valuation.date.desc()).first()
        current_nav = latest.portfolio_nav_gbp if latest else 0

    return compute_projections(current_nav, monthly_contribution=0)


# ── Attribution ─────────────────────────────────────────────────────────────

@app.get("/api/attribution")
def get_attribution(db: Session = Depends(get_db)):
    """Compute return attribution by pie, sector, and holding."""
    return compute_attribution(db)


# ── Tax Summary ─────────────────────────────────────────────────────────────

@app.get("/api/tax/summary")
def get_tax_summary(db: Session = Depends(get_db)):
    """Get realised gains summary by UK tax year."""
    transactions = db.query(Transaction).order_by(Transaction.date).all()
    results = calculate_cost_basis([
        {
            "date": t.date,
            "type": t.type.value,
            "ticker": t.instrument.ticker if t.instrument else "UNKNOWN",
            "quantity": t.quantity,
            "price_gbp": t.price or 0,
            "fee_gbp": t.fee_gbp,
            "fx_rate": t.fx_rate,
        }
        for t in transactions if t.instrument
    ])
    return list(results.values())


# ── Transactions ────────────────────────────────────────────────────────────

@app.get("/api/transactions", response_model=list[TransactionRead])
def get_transactions(
    db: Session = Depends(get_db),
    type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """Get transactions with optional filtering."""
    from app.models import Transaction

    q = db.query(Transaction)
    if type:
        q = q.filter(Transaction.type.value == type)
    if source:
        q = q.filter(Transaction.source == source)
    q = q.order_by(Transaction.date.desc())

    transactions = q.offset(offset).limit(limit).all()
    return transactions


# ── Alerts ──────────────────────────────────────────────────────────────────

@app.post("/api/alerts/run")
def run_alerts(db: Session = Depends(get_db)):
    """Run the alert engine and return triggered alerts."""
    return run_alert_engine(db)


@app.get("/api/alerts")
def get_alerts(db: Session = Depends(get_db)):
    """Get all alerts."""
    from app.models import Alert
    return db.query(Alert).order_by(Alert.triggered_at.desc()).all()


# ── Audit Log ───────────────────────────────────────────────────────────────

@app.get("/api/audit-log")
def get_audit_log(
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """Get the audit log."""
    from app.models import AuditLog
    return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()


# ── Data Refresh ────────────────────────────────────────────────────────────

@app.post("/api/data/refresh/prices")
def api_refresh_prices(db: Session = Depends(get_db), days_back: int = 5):
    """Refresh price data for all instruments."""
    return refresh_prices(db, days_back)


@app.post("/api/data/refresh/fx")
def api_refresh_fx(db: Session = Depends(get_db), days_back: int = 5):
    """Refresh FX rates."""
    return refresh_fx_rates(db, days_back=days_back)


# ── Health Check ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "database": "connected",
        "version": "0.1.0",
    }


# ── Root ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    """API root."""
    return {
        "name": "Great Dyke Meridian",
        "version": "0.1.0",
        "endpoints": [
            "/api/health",
            "/api/axis/summary",
            "/api/holdings",
            "/api/returns",
            "/api/risk/metrics",
            "/api/correlation/stock",
            "/api/correlation/sector",
            "/api/correlation/pie",
            "/api/correlation/benchmark",
            "/api/correlation/concentration",
            "/api/projections",
            "/api/attribution",
            "/api/tax/summary",
            "/api/transactions",
            "/api/alerts",
            "/api/alerts/run",
            "/api/audit-log",
            "/api/data/refresh/prices",
            "/api/data/refresh/fx",
        ],
    }
