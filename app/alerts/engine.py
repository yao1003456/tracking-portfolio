"""
Alerts Engine — Stage 4/5

Evaluates configurable alert rules against current portfolio state.
Stores alerts in the DB and returns triggered alerts.

Rules:
- Drawdown from peak exceeds X% (pie level and total)
- Daily move exceeds X% for any holding
- Single holding weight exceeds X% of NAV
- Correlation alerts (avg pairwise > threshold, held pair corr > 0.85)
- VaR 95 exceeds X% of NAV
- Price data older than 1 trading day
- Thesis review due
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.calculations.holdings import compute_holdings, compute_risk_metrics
from app.calculations.correlation import compute_risk_concentration
from app.services.price_service import check_price_freshness

logger = logging.getLogger(__name__)


def run_alert_engine(db: Session) -> list[dict]:
    """
    Run all alert rules and return triggered alerts.

    Returns:
        list of alert dicts: {rule, message, entity_type, entity_id, threshold}
    """
    alerts = []

    # 1. Drawdown alerts
    alerts.extend(_check_drawdown_alerts(db))

    # 2. Daily move alerts
    alerts.extend(_check_daily_move_alerts(db))

    # 3. Concentration alerts
    alerts.extend(_check_concentration_alerts(db))

    # 4. Correlation alerts
    alerts.extend(_check_correlation_alerts(db))

    # 5. VaR alerts
    alerts.extend(_check_var_alerts(db))

    # 6. Data freshness alerts
    alerts.extend(_check_freshness_alerts(db))

    # 7. Thesis review alerts
    alerts.extend(_check_thesis_alerts(db))

    # Store in DB
    _store_alerts(db, alerts)

    return alerts


def _check_drawdown_alerts(db: Session) -> list[dict]:
    """Check drawdown thresholds."""
    from app.models import Valuation, Pie

    alerts = []

    # Total portfolio drawdown
    valuations = (
        db.query(Valuation)
        .filter(Valuation.pie_id.is_(None))
        .order_by(Valuation.date)
        .all()
    )

    if len(valuations) >= 2:
        nav_series = [v.portfolio_nav_gbp for v in valuations]
        peak = max(nav_series)
        current = nav_series[-1]
        dd = (current / peak - 1) * 100

        if dd < -5:  # Default threshold
            alerts.append({
                "rule": "portfolio_drawdown",
                "message": f"Portfolio drawdown {dd:.1f}% from peak",
                "entity_type": "portfolio",
                "entity_id": None,
                "threshold": -5.0,
            })

    # Per-pie drawdown
    pies = db.query(Pie).all()
    for pie in pies:
        pie_vals = (
            db.query(Valuation)
            .filter(Valuation.pie_id == pie.id)
            .order_by(Valuation.date)
            .all()
        )
        if len(pie_vals) >= 2:
            nav = [v.holding_value_gbp or v.portfolio_nav_gbp for v in pie_vals]
            peak = max(nav)
            current = nav[-1]
            dd = (current / peak - 1) * 100
            if dd < -5:
                alerts.append({
                    "rule": "pie_drawdown",
                    "message": f"{pie.name} drawdown {dd:.1f}% from peak",
                    "entity_type": "pie",
                    "entity_id": pie.id,
                    "threshold": -5.0,
                })

    return alerts


def _check_daily_move_alerts(db: Session) -> list[dict]:
    """Check for large daily moves."""
    from app.models import Price, Instrument

    alerts = []
    yesterday = date.today()
    two_days_ago = date.today()

    # Get latest prices
    prices = db.query(Price).order_by(Price.date.desc()).limit(2).all()
    if len(prices) >= 2:
        current = prices[0]
        previous = prices[1]
        daily_move = (current.close / previous.close - 1) * 100

        if abs(daily_move) > 5:  # Default 5% threshold
            inst = db.query(Instrument).filter(Instrument.id == current.instrument_id).first()
            alerts.append({
                "rule": "daily_move",
                "message": f"{inst.ticker} moved {daily_move:.1f}% in one day",
                "entity_type": "holding",
                "entity_id": current.instrument_id,
                "threshold": 5.0,
            })

    return alerts


def _check_concentration_alerts(db: Session) -> list[dict]:
    """Check concentration thresholds."""
    from app.models import Setting

    holdings = compute_holdings(db)
    alerts = []

    for h in holdings:
        if h["weight"] > 20:  # Single holding > 20% of NAV
            alerts.append({
                "rule": "concentration",
                "message": f"{h['ticker']} is {h['weight']:.1f}% of NAV",
                "entity_type": "holding",
                "entity_id": None,
                "threshold": 20.0,
            })

    return alerts


def _check_correlation_alerts(db: Session) -> list[dict]:
    """Check correlation thresholds."""
    from app.models import Alert

    concentration = compute_risk_concentration(db)

    alerts = []

    # Average pairwise correlation
    avg_corr = concentration.get("average_pairwise_correlation", 0)
    if avg_corr > settings.correlation_alert_threshold:
        alerts.append({
            "rule": "avg_pairwise_correlation",
            "message": f"Average pairwise correlation {avg_corr:.3f} exceeds {settings.correlation_alert_threshold}",
            "entity_type": "portfolio",
            "entity_id": None,
            "threshold": settings.correlation_alert_threshold,
        })

    # Effective bets
    eff_bets = concentration.get("effective_number_of_bets", 0)
    if eff_bets < settings.effective_bets_min:
        alerts.append({
            "rule": "effective_bets_low",
            "message": f"Effective number of bets {eff_bets:.1f} below minimum {settings.effective_bets_min}",
            "entity_type": "portfolio",
            "entity_id": None,
            "threshold": float(settings.effective_bets_min),
        })

    # Top correlated pairs
    for pair in concentration.get("top_correlated_pairs", []):
        if pair.get("correlation", 0) > 0.85:
            alerts.append({
                "rule": "held_pair_high_correlation",
                "message": f"{pair['pair'][0]}/{pair['pair'][1]} correlation {pair['correlation']:.3f}",
                "entity_type": "holding",
                "entity_id": None,
                "threshold": 0.85,
            })

    return alerts


def _check_var_alerts(db: Session) -> list[dict]:
    """Check VaR thresholds."""
    risk = compute_risk_metrics(db)
    alerts = []

    var_95 = abs(risk.get("var_95", 0))
    if var_95 > 3:  # VaR 95 > 3% of NAV
        alerts.append({
            "rule": "var_95_high",
            "message": f"VaR 95% at {var_95:.2f}% of NAV",
            "entity_type": "portfolio",
            "entity_id": None,
            "threshold": 3.0,
        })

    return alerts


def _check_freshness_alerts(db: Session) -> list[dict]:
    """Check price data freshness."""
    freshness = check_price_freshness(db)
    alerts = []

    for f in freshness:
        alerts.append({
            "rule": "stale_price",
            "message": f["message"],
            "entity_type": "holding",
            "entity_id": None,
            "threshold": None,
        })

    return alerts


def _check_thesis_alerts(db: Session) -> list[dict]:
    """Check thesis review dates."""
    from app.models import ThesisNote

    alerts = []
    today = date.today()

    notes = db.query(ThesisNote).filter(
        ThesisNote.review_date <= today,
        ThesisNote.review_date.isnot(None),
    ).all()

    for note in notes:
        alerts.append({
            "rule": "thesis_review_due",
            "message": f"Thesis review due for {note.instrument.ticker if note.instrument else 'unknown'}",
            "entity_type": "thesis",
            "entity_id": note.id,
            "threshold": None,
        })

    return alerts


def _store_alerts(db: Session, alerts: list[dict]) -> None:
    """Store triggered alerts in the database."""
    from app.models import Alert

    for a in alerts:
        alert = Alert(
            rule=a["rule"],
            threshold=a.get("threshold"),
            triggered_at=datetime.now(timezone.utc),
            message=a.get("message"),
            entity_type=a.get("entity_type"),
            entity_id=a.get("entity_id"),
        )
        db.add(alert)

    db.commit()
