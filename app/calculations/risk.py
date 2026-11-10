"""
Risk Calculations Module

Computes:
- Sharpe ratio (using UK Bank Rate)
- Sortino ratio
- Max drawdown with peak/trough dates
- Historical VaR (95%, 99%) and Expected Shortfall
- Beta and Jensen's alpha (CAPM regression)
- Concentration metrics (HHI, effective N, top-5/10)
- Currency exposure
"""

import math
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.calculations.holdings import compute_holdings, _get_total_nav


def compute_risk_metrics(db: Session, window_days: int = 252) -> dict:
    """
    Compute all risk metrics for the portfolio.

    Uses daily log returns over a configurable window (default 252 trading days = 1 year).
    Risk-free rate is the UK Bank Rate.
    """
    # Get NAV series from valuations
    from app.models import Valuation, RiskFreeRate

    valuations = (
        db.query(Valuation)
        .filter(Valuation.pie_id.is_(None))
        .order_by(Valuation.date)
        .all()
    )

    if len(valuations) < window_days:
        return _empty_risk(window_days)

    nav_series = pd.Series(
        [v.portfolio_nav_gbp for v in valuations],
        index=[v.date for v in valuations],
    ).sort_index().tail(window_days)

    if len(nav_series) < 30:
        return _empty_risk(window_days)

    # Daily log returns
    daily_returns = np.log(nav_series / nav_series.shift(1)).dropna()

    # Risk-free rate (daily)
    rf_annual = _get_bank_rate(db)
    rf_daily = rf_annual / 252

    excess_returns = daily_returns - rf_daily

    # ── Sharpe Ratio ───────────────────────────────────────────────────
    sharpe = 0.0
    if excess_returns.std() > 0:
        sharpe = float(excess_returns.mean() / excess_returns.std() * math.sqrt(252))

    # ── Sortino Ratio ──────────────────────────────────────────────────
    downside = excess_returns[excess_returns < 0]
    sortino = 0.0
    if len(downside) > 0:
        downside_std = np.sqrt(np.mean(downside ** 2))
        if downside_std > 0:
            sortino = float(excess_returns.mean() / downside_std * math.sqrt(252))

    # ── Max Drawdown ───────────────────────────────────────────────────
    cumulative = (1 + daily_returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max

    max_dd = float(drawdown.min()) * 100
    dd_peak_idx = drawdown.argmax()
    dd_trough = drawdown.iloc[dd_peak_idx:]
    dd_trough_idx = dd_peak_idx + dd_trough.idxmin()

    peak_date = cumulative.index[dd_peak_idx] if dd_peak_idx < len(cumulative) else None
    trough_date = cumulative.index[dd_trough_idx] if dd_trough_idx < len(cumulative) else None

    current_dd = float(drawdown.iloc[-1]) * 100 if len(drawdown) > 0 else 0

    # ── VaR & Expected Shortfall ───────────────────────────────────────
    var_95 = float(np.percentile(daily_returns, 5)) * 100
    var_99 = float(np.percentile(daily_returns, 1)) * 100

    es_95 = float(downside[downside <= var_95 / 100].mean() * 100) if len(downside[downside <= var_95 / 100]) > 0 else 0
    tail_99 = daily_returns[daily_returns <= var_99 / 100]
    es_99 = float(tail_99.mean() * 100) if len(tail_99) > 0 else 0

    # ── Beta & Alpha vs Benchmarks ─────────────────────────────────────
    vuag_ret, iwda_ret = _get_benchmark_returns(db, window_days)

    beta_v, alpha_v, r2_v = _capm(daily_returns, vuag_ret)
    beta_i, alpha_i, r2_i = _capm(daily_returns, iwda_ret)

    # ── Concentration ──────────────────────────────────────────────────
    holdings = compute_holdings(db)
    weights = np.array([h["weight"] for h in holdings]) if holdings else np.array([0.0])
    weights = weights[weights > 0]

    top5 = float(np.sum(np.sort(weights)[-5:])) if len(weights) >= 5 else float(np.sum(weights))
    top10 = float(np.sum(np.sort(weights)[-10:])) if len(weights) >= 10 else float(np.sum(weights))
    hhi = float(np.sum(weights ** 2)) if len(weights) > 0 else 0
    eff_n = float(1 / hhi) if hhi > 0 else float(len(weights))

    # ── Currency Exposure ──────────────────────────────────────────────
    currency = _currency_exposure(db, holdings)

    # ── Drawdown Series ────────────────────────────────────────────────
    dd_series = [
        {"date": d.strftime("%Y-%m-%d"), "drawdown": round(float(v) * 100, 4)}
        for d, v in drawdown.items()
    ]

    return {
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown": round(max_dd, 4),
        "max_drawdown_peak_date": peak_date.isoformat() if peak_date else None,
        "max_drawdown_trough_date": trough_date.isoformat() if trough_date else None,
        "current_drawdown": round(current_dd, 4),
        "var_95": round(var_95, 4),
        "var_99": round(var_99, 4),
        "expected_shortfall_95": round(es_95, 4),
        "expected_shortfall_99": round(es_99, 4),
        "beta_vuag": round(beta_v, 4),
        "alpha_vuag": round(alpha_v, 4),
        "r_squared_vuag": round(r2_v, 4),
        "beta_iwda": round(beta_i, 4),
        "alpha_iwda": round(alpha_i, 4),
        "r_squared_iwda": round(r2_i, 4),
        "concentration_top5": round(top5, 2),
        "concentration_top10": round(top10, 2),
        "hhi": round(hhi, 4),
        "effective_holdings": round(eff_n, 2),
        "currency_exposure": currency,
        "drawdown_series": dd_series,
        "observation_count": len(daily_returns),
    }


def _get_bank_rate(db: Session) -> float:
    """Get the latest UK Bank Rate."""
    from app.models import RiskFreeRate
    rate = db.query(RiskFreeRate).order_by(RiskFreeRate.date.desc()).first()
    return rate.rate / 100 if rate else 0.05


def _get_benchmark_returns(db: Session, window: int) -> tuple:
    """Get benchmark log returns."""
    from app.models import Benchmark

    vuag = db.query(Benchmark).filter(Benchmark.ticker == "VUAG.L").order_by(Benchmark.date).tail(window)
    iwda = db.query(Benchmark).filter(Benchmark.ticker == "IWDA.L").order_by(Benchmark.date).tail(window)

    vuag_ret = np.log(pd.Series([p.close for p in vuag]) / pd.Series([p.close for p in vuag]).shift(1)).dropna().values if len(vuag) > 1 else np.array([])
    iwda_ret = np.log(pd.Series([p.close for p in iwda]) / pd.Series([p.close for p in iwda]).shift(1)).dropna().values if len(iwda) > 1 else np.array([])

    return vuag_ret, iwda_ret


def _capm(port_returns: np.ndarray, bench_returns: np.ndarray) -> tuple:
    """CAPM regression."""
    min_len = min(len(port_returns), len(bench_returns))
    if min_len < 10:
        return 0.0, 0.0, 0.0

    p = port_returns[:min_len]
    b = bench_returns[:min_len]

    slope, intercept = np.polyfit(b, p, 1)
    alpha = (intercept - slope * np.mean(b)) * 252 * 100
    predicted = intercept + slope * b
    ss_res = np.sum((p - predicted) ** 2)
    ss_tot = np.sum((p - np.mean(p)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    beta = slope * math.sqrt(252)

    return round(float(beta), 4), round(float(alpha), 4), round(float(r2), 4)


def _currency_exposure(db: Session, holdings: list[dict]) -> dict:
    """Compute currency exposure."""
    from app.models import Instrument
    exposure = {"GBP": 0.0, "USD": 0.0, "EUR": 0.0, "OTHER": 0.0}
    total = sum(h["market_value_gbp"] for h in holdings)

    for h in holdings:
        inst = db.query(Instrument).filter(Instrument.ticker == h["ticker"]).first()
        curr = (inst.listing_currency if inst else "GBP").upper()
        if curr in exposure:
            exposure[curr] += h["market_value_gbp"]
        else:
            exposure["OTHER"] += h["market_value_gbp"]

    if total > 0:
        for k in exposure:
            exposure[k] = round(exposure[k] / total * 100, 2)

    return exposure


def _empty_risk(window: int) -> dict:
    """Return empty risk metrics."""
    return {
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0,
        "max_drawdown": 0.0, "max_drawdown_peak_date": None,
        "max_drawdown_trough_date": None, "current_drawdown": 0.0,
        "var_95": 0.0, "var_99": 0.0,
        "expected_shortfall_95": 0.0, "expected_shortfall_99": 0.0,
        "beta_vuag": 0.0, "alpha_vuag": 0.0, "r_squared_vuag": 0.0,
        "beta_iwda": 0.0, "alpha_iwda": 0.0, "r_squared_iwda": 0.0,
        "concentration_top5": 0.0, "concentration_top10": 0.0,
        "hhi": 0.0, "effective_holdings": 0.0,
        "currency_exposure": {}, "drawdown_series": [],
        "observation_count": 0,
    }
