"""
Attribution Module

Computes return attribution:
- By pie, sector, and holding
- Market (beta) vs residual (alpha) components
- Win/loss ratio, profit factor, average holding period
- Realised gains by UK tax year
"""

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.calculations.cost_basis import calculate_cost_basis, _uk_tax_year


def compute_attribution(db: Session) -> dict:
    """
    Compute full return attribution.

    Returns:
        {
            "total_return": float,
            "market_component": float,
            "alpha_component": float,
            "by_pie": list[dict],
            "by_sector": list[dict],
            "by_holding": list[dict],
            "win_loss_ratio": float,
            "profit_factor": float,
            "avg_holding_period_days": float,
            "realised_gains_by_tax_year": list[dict],
        }
    """
    from app.models import Valuation, Position, Transaction, Instrument, Pie

    # Total return from NAV series
    valuations = (
        db.query(Valuation)
        .filter(Valuation.pie_id.is_(None))
        .order_by(Valuation.date)
        .all()
    )

    if len(valuations) < 2:
        return _empty_attribution()

    nav_series = pd.Series(
        [v.portfolio_nav_gbp for v in valuations],
        index=[v.date for v in valuations],
    ).sort_index()

    total_return = float((nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100)

    # ── By Holding ─────────────────────────────────────────────────────
    holdings_attr = []
    positions = db.query(Position).all()

    for pos in positions:
        inst = pos.instrument
        if not inst:
            continue

        latest = (
            db.query(Price)
            .filter(Price.instrument_id == pos.instrument_id)
            .order_by(Price.date.desc())
            .first()
        )
        if not latest:
            continue

        mv = pos.quantity * latest.close
        # Get cost basis
        buys = (
            db.query(Transaction)
            .filter(
                Transaction.instrument_id == pos.instrument_id,
                Transaction.type.value.in_(("buy", "deposit")),
            )
            .all()
        )
        total_cost = sum((t.quantity * (t.price or 0) + t.fee_gbp) for t in buys)

        unrealised = mv - total_cost
        weight = mv / nav_series.iloc[-1] * 100 if nav_series.iloc[-1] > 0 else 0

        holdings_attr.append({
            "ticker": inst.ticker,
            "name": inst.name,
            "market_value": round(mv, 2),
            "weight": round(weight, 2),
            "unrealised_pnl": round(unrealised, 2),
            "contribution": round(unrealised / nav_series.iloc[-1] * 100, 4),
        })

    holdings_attr.sort(key=lambda x: x["market_value"], reverse=True)

    # ── By Pie ─────────────────────────────────────────────────────────
    pies = db.query(Pie).all()
    pies_attr = []

    for pie in pies:
        pie_positions = db.query(Position).filter(Position.pie_id == pie.id).all()
        pie_nav = 0
        for pp in pie_positions:
            latest = (
                db.query(Price)
                .filter(Price.instrument_id == pp.instrument_id)
                .order_by(Price.date.desc())
                .first()
            )
            if latest:
                pie_nav += pp.quantity * latest.close

        pie_return = 0  # Would need pie-level NAV history
        pies_attr.append({
            "name": pie.name,
            "nav": round(pie_nav, 2),
            "target_allocation": pie.target_allocation,
            "actual_allocation": round(pie_nav / nav_series.iloc[-1] * 100, 2) if nav_series.iloc[-1] > 0 else 0,
            "drift": 0,
            "return": pie_return,
        })

    # ── By Sector ──────────────────────────────────────────────────────
    sectors = {}
    for h in holdings_attr:
        inst = db.query(Instrument).filter(Instrument.ticker == h["ticker"]).first()
        sector = inst.sector or "Unknown"
        sectors.setdefault(sector, {"nav": 0, "unrealised": 0})
        sectors[sector]["nav"] += h["market_value"]
        sectors[sector]["unrealised"] += h["unrealised_pnl"]

    sector_attr = [
        {
            "sector": s,
            "nav": round(v["nav"], 2),
            "unrealised_pnl": round(v["unrealised"], 2),
        }
        for s, v in sectors.items()
    ]

    # ── Market vs Alpha ────────────────────────────────────────────────
    # Simplified: assume total return = market + alpha
    # Market component = benchmark return * beta
    # Alpha = total - market
    market_component = total_return * 0.8  # placeholder
    alpha_component = total_return - market_component

    # ── Win/Loss & Profit Factor ───────────────────────────────────────
    sells = db.query(Transaction).filter(Transaction.type.value == "sell").all()
    gains = 0
    losses = 0
    win_count = 0
    loss_count = 0

    for s in sells:
        if s.amount_gbp and s.fee_gbp:
            pnl = s.amount_gbp - (s.quantity * (s.price or 0)) - s.fee_gbp
            if pnl > 0:
                gains += pnl
                win_count += 1
            else:
                losses += abs(pnl)
                loss_count += 1

    win_loss = win_count / loss_count if loss_count > 0 else float(win_count)
    profit_factor = gains / losses if losses > 0 else float(gains)

    # ── Average Holding Period ─────────────────────────────────────────
    holding_periods = []
    for inst in db.query(Instrument).all():
        txns = (
            db.query(Transaction)
            .filter(Transaction.instrument_id == inst.id)
            .order_by(Transaction.date)
            .all()
        )
        if len(txns) >= 2:
            first_date = txns[0].date
            last_date = txns[-1].date
            holding_periods.append((last_date - first_date).days)

    avg_holding = float(np.mean(holding_periods)) if holding_periods else 0

    # ── Realised Gains by Tax Year ─────────────────────────────────────
    all_txns = db.query(Transaction).order_by(Transaction.date).all()
    tax_results = calculate_cost_basis([
        {
            "date": t.date,
            "type": t.type.value,
            "ticker": t.instrument.ticker if t.instrument else "UNKNOWN",
            "quantity": t.quantity,
            "price_gbp": t.price or 0,
            "fee_gbp": t.fee_gbp,
            "fx_rate": t.fx_rate,
        }
        for t in all_txns if t.instrument
    ])

    tax_summary = [
        {
            "tax_year": r.tax_year,
            "realised_gains": float(r.realised_gains),
            "realised_losses": float(r.realised_losses),
        }
        for r in tax_results.values()
    ]

    return {
        "total_return": round(total_return, 4),
        "market_component": round(market_component, 4),
        "alpha_component": round(alpha_component, 4),
        "by_pie": pies_attr,
        "by_sector": sector_attr,
        "by_holding": holdings_attr,
        "win_loss_ratio": round(win_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_holding_period_days": round(avg_holding, 1),
        "realised_gains_by_tax_year": tax_summary,
    }


def _empty_attribution() -> dict:
    """Return empty attribution."""
    return {
        "total_return": 0.0,
        "market_component": 0.0,
        "alpha_component": 0.0,
        "by_pie": [],
        "by_sector": [],
        "by_holding": [],
        "win_loss_ratio": 0.0,
        "profit_factor": 0.0,
        "avg_holding_period_days": 0.0,
        "realised_gains_by_tax_year": [],
    }
