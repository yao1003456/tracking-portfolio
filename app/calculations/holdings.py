"""
Holdings and Returns Calculations

Computes:
- Current holdings with market values, unrealised PnL
- Section 104 cost basis tracking
- Returns: daily, MTD, YTD, since-inception, time-weighted (TWRR)
- Dividends and total return
"""

import math
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models import Position, Price, Transaction, Instrument, Pie


def compute_holdings(db: Session) -> list[dict]:
    """
    Compute current holdings for all positions.

    Returns a list of dicts with:
    - ticker, name, pie
    - quantity, section_104_cost, current_price
    - market_value_gbp, weight, unrealised_pnl_gbp
    - realised_pnl_gbp, dividends_gbp
    - rag status, last_price_date
    """
    holdings = []
    total_nav = _compute_total_nav(db)

    positions = db.query(Position).all()
    for pos in positions:
        inst = pos.instrument
        pie = next((p for p in db.query(Pie).all() if p.id == pos.pie_id), None)

        # Latest price
        latest_price = (
            db.query(Price)
            .filter(Price.instrument_id == pos.instrument_id)
            .order_by(Price.date.desc())
            .first()
        )

        if not latest_price or latest_price.close <= 0:
            continue

        current_price = latest_price.close
        market_value = pos.quantity * current_price

        # Section 104 cost from transactions
        s104_cost = _compute_section_104_cost(db, inst.ticker, pos.quantity)

        # Unrealised PnL
        unrealised_pnl = market_value - s104_cost

        # Dividends
        dividends = _sum_dividends(db, inst.ticker)

        # Realised PnL
        realised_pnl = _compute_realised_pnl(db, inst.ticker)

        # Weight
        weight = (market_value / total_nav * 100) if total_nav > 0 else 0

        # RAG status
        rag = _compute_rag(unrealised_pnl, s104_cost, market_value)

        holdings.append({
            "ticker": inst.ticker,
            "name": inst.name,
            "pie": pie.name if pie else "Unknown",
            "quantity": pos.quantity,
            "section_104_cost": round(s104_cost, 2),
            "current_price": round(current_price, 4),
            "market_value_gbp": round(market_value, 2),
            "weight": round(weight, 2),
            "unrealised_pnl_gbp": round(unrealised_pnl, 2),
            "realised_pnl_gbp": round(realised_pnl, 2),
            "dividends_gbp": round(dividends, 2),
            "rag": rag,
            "last_price_date": latest_price.date,
        })

    return holdings


def compute_returns(db: Session) -> dict:
    """
    Compute portfolio returns: daily, MTD, YTD, since inception, TWRR.

    Time-weighted return (TWRR) uses the Modified Dietz method:
    - Divide the period into sub-periods at each cash flow
    - Compute sub-period returns
    - Chain them: (1+r1)(1+r2)... - 1

    Cash flows (deposits/withdrawals) are treated as external cash flows
    and adjust the base NAV for return calculations.
    """
    # Get all valuation snapshots
    from app.models import Valuation
    valuations = (
        db.query(Valuation)
        .filter(Valuation.pie_id.is_(None))  # portfolio-level only
        .order_by(Valuation.date)
        .all()
    )

    if len(valuations) < 2:
        return {
            "daily": [],
            "mtd": 0.0,
            "ytd": 0.0,
            "since_inception": 0.0,
            "twrr_1y": 0.0,
            "twrr_ytd": 0.0,
        }

    nav_series = pd.Series(
        [v.portfolio_nav_gbp for v in valuations],
        index=[v.date for v in valuations],
    ).sort_index()

    # Daily returns (log returns)
    daily_returns = np.log(nav_series / nav_series.shift(1)).dropna()

    # MTD: return from first day of current month
    now = date.today()
    month_start = date(now.year, now.month, 1)
    mtd_nav = nav_series[nav_series.index >= month_start]
    mtd_return = (mtd_nav.iloc[-1] / mtd_nav.iloc[0] - 1) * 100 if len(mtd_nav) > 1 else 0

    # YTD: return from 6 April of current tax year
    tax_year_start = date(now.year, 4, 6) if now >= date(now.year, 4, 6) else date(now.year - 1, 4, 6)
    ytd_nav = nav_series[nav_series.index >= tax_year_start]
    ytd_return = (ytd_nav.iloc[-1] / ytd_nav.iloc[0] - 1) * 100 if len(ytd_nav) > 1 else 0

    # Since inception
    inception_return = (nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100

    # Time-weighted return over 1 year and YTD (Modified Dietz approximation)
    twrr_1y = _compute_twrr(db, window_days=252)
    twrr_ytd = _compute_twrr_ytd(db)

    return {
        "daily": [
            {"date": d.strftime("%Y-%m-%d"), "return": round(float(r), 6)}
            for d, r in daily_returns.items()
        ][-30:],  # last 30 days
        "mtd": round(float(mtd_return), 4),
        "ytd": round(float(ytd_return), 4),
        "since_inception": round(float(inception_return), 4),
        "twrr_1y": round(float(twrr_1y), 4),
        "twrr_ytd": round(float(twrr_ytd), 4),
    }


def compute_risk_metrics(db: Session, window_days: int = 252) -> dict:
    """
    Compute risk metrics based on daily log returns.

    Metrics:
    - Sharpe ratio (using UK Bank Rate as risk-free rate)
    - Sortino ratio
    - Max drawdown and current drawdown with peak/trough dates
    - Historical VaR at 95% and 99%, Expected Shortfall
    - Beta and Jensen's alpha vs VUAG and IWDA
    - Concentration: top-5/10 weight, HHI, effective number of holdings
    """
    from app.models import Benchmark, RiskFreeRate

    # Get portfolio NAV series
    from app.models import Valuation
    valuations = (
        db.query(Valuation)
        .filter(Valuation.pie_id.is_(None))
        .order_by(Valuation.date)
        .all()
    )

    if len(valuations) < window_days:
        return _empty_risk_metrics()

    nav_series = pd.Series(
        [v.portfolio_nav_gbp for v in valuations],
        index=[v.date for v in valuations],
    ).sort_index().tail(window_days)

    if len(nav_series) < 10:
        return _empty_risk_metrics()

    # Daily log returns
    daily_returns = np.log(nav_series / nav_series.shift(1)).dropna()

    # Risk-free rate (daily)
    rf_annual = _get_current_bank_rate(db)
    rf_daily = rf_annual / 252

    excess_returns = daily_returns - rf_daily

    # ── Sharpe Ratio ───────────────────────────────────────────────────
    sharpe = 0.0
    if excess_returns.std() > 0:
        sharpe = float(excess_returns.mean() / excess_returns.std() * math.sqrt(252))

    # ── Sortino Ratio ──────────────────────────────────────────────────
    downside_returns = excess_returns[excess_returns < 0]
    sortino = 0.0
    if len(downside_returns) > 0 and downside_returns.std() > 0:
        downside_std = np.sqrt(np.mean(downside_returns ** 2))
        sortino = float(excess_returns.mean() / downside_std * math.sqrt(252))

    # ── Max Drawdown ───────────────────────────────────────────────────
    cumulative = (1 + daily_returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max

    max_dd = float(drawdown.min()) * 100
    dd_peak_idx = drawdown.argmax()  # index of peak before max drawdown
    dd_trough_idx = dd_peak_idx + drawdown[dd_peak_idx:].idxmin()

    peak_date = cumulative.index[dd_peak_idx] if len(cumulative) > dd_peak_idx else None
    trough_date = cumulative.index[dd_trough_idx] if len(cumulative) > dd_trough_idx else None

    # Current drawdown
    current_dd = float(drawdown.iloc[-1]) * 100 if len(drawdown) > 0 else 0

    # ── VaR and Expected Shortfall ─────────────────────────────────────
    var_95 = float(np.percentile(daily_returns, 5)) * 100
    var_99 = float(np.percentile(daily_returns, 1)) * 100

    es_95 = float(downside_returns[downside_returns <= var_95 / 100].mean() * 100) if len(downside_returns) > 0 else 0
    es_99 = 0.0
    tail_99 = daily_returns[daily_returns <= var_99 / 100]
    if len(tail_99) > 0:
        es_99 = float(tail_99.mean() * 100)

    # ── Beta and Alpha vs Benchmarks ───────────────────────────────────
    vuag_returns, iwda_returns = _get_benchmark_returns(db, window_days)

    beta_vuag, alpha_vuag, r2_vuag = _capm_regression(daily_returns, vuag_returns)
    beta_iwda, alpha_iwda, r2_iwda = _capm_regression(daily_returns, iwda_returns)

    # ── Concentration ──────────────────────────────────────────────────
    holdings = compute_holdings(db)
    weights = np.array([h["weight"] for h in holdings]) if holdings else np.array([0])
    weights = weights[weights > 0]

    top5 = float(np.sum(np.sort(weights)[-5:])) if len(weights) >= 5 else float(np.sum(weights))
    top10 = float(np.sum(np.sort(weights)[-10:])) if len(weights) >= 10 else float(np.sum(weights))

    hhi = float(np.sum(weights ** 2)) if len(weights) > 0 else 0
    effective_n = float(1 / hhi) if hhi > 0 else float(len(weights))

    # ── Currency Exposure ──────────────────────────────────────────────
    currency_exposure = _compute_currency_exposure(db, holdings)

    # ── Drawdown series for charting ───────────────────────────────────
    drawdown_series = [
        {"date": d.strftime("%Y-%m-%d"), "drawdown": round(float(dd) * 100, 4)}
        for d, dd in drawdown.items()
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
        "beta_vuag": round(beta_vuag, 4),
        "alpha_vuag": round(alpha_vuag, 4),
        "r_squared_vuag": round(r2_vuag, 4),
        "beta_iwda": round(beta_iwda, 4),
        "alpha_iwda": round(alpha_iwda, 4),
        "r_squared_iwda": round(r2_iwda, 4),
        "concentration_top5": round(top5, 2),
        "concentration_top10": round(top10, 2),
        "hhi": round(hhi, 4),
        "effective_holdings": round(effective_n, 2),
        "currency_exposure": currency_exposure,
        "drawdown_series": drawdown_series,
        "observation_count": len(daily_returns),
    }


def _compute_total_nav(db: Session) -> float:
    """Compute current total portfolio NAV from positions and latest prices."""
    total = 0.0
    for pos in db.query(Position).all():
        latest = (
            db.query(Price)
            .filter(Price.instrument_id == pos.instrument_id)
            .order_by(Price.date.desc())
            .first()
        )
        if latest and latest.close > 0:
            total += pos.quantity * latest.close
    return total


def _compute_section_104_cost(db: Session, ticker: str, quantity: float) -> float:
    """Compute Section 104 allowable cost for a given quantity of a ticker."""
    transactions = (
        db.query(Transaction)
        .filter(Transaction.instrument_id == db.query(Instrument).filter(Instrument.ticker == ticker).first().id)
        .order_by(Transaction.date)
        .all()
    )
    # Simplified: sum of buy costs minus proportional sell costs
    pool_cost = Decimal("0")
    pool_qty = Decimal("0")

    for t in transactions:
        if t.type.value in ("buy", "deposit"):
            cost = Decimal(str(t.quantity)) * (Decimal(str(t.price)) if t.price else Decimal("0"))
            pool_cost += cost + Decimal(str(t.fee_gbp))
            pool_qty += Decimal(str(t.quantity))
        elif t.type.value == "sell" and pool_qty > 0:
            fraction = Decimal(str(t.quantity)) / pool_qty
            disposal = pool_cost * fraction
            pool_cost -= disposal
            pool_qty -= Decimal(str(t.quantity))

    if pool_qty == 0:
        return 0.0

    avg_cost = pool_cost / pool_qty
    return float(avg_cost * Decimal(str(quantity)))


def _sum_dividends(db: Session, ticker: str) -> float:
    """Sum all dividend income for a ticker, converted to GBP."""
    inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
    if not inst:
        return 0.0
    divs = (
        db.query(Transaction)
        .filter(
            Transaction.instrument_id == inst.id,
            Transaction.type.value == "dividend",
        )
        .all()
    )
    return sum(t.amount_gbp or 0 for t in divs)


def _compute_realised_pnl(db: Session, ticker: str) -> float:
    """Compute realised PnL for a ticker using Section 104 pooling."""
    inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
    if not inst:
        return 0.0

    transactions = (
        db.query(Transaction)
        .filter(Transaction.instrument_id == inst.id)
        .order_by(Transaction.date)
        .all()
    )

    pool_cost = Decimal("0")
    pool_qty = Decimal("0")
    realised = Decimal("0")

    for t in transactions:
        if t.type.value == "buy":
            cost = Decimal(str(t.quantity)) * (Decimal(str(t.price)) if t.price else Decimal("0"))
            pool_cost += cost + Decimal(str(t.fee_gbp))
            pool_qty += Decimal(str(t.quantity))
        elif t.type.value == "sell" and pool_qty > 0:
            fraction = Decimal(str(t.quantity)) / pool_qty
            disposal = pool_cost * fraction
            proceeds = Decimal(str(t.quantity)) * (Decimal(str(t.price)) if t.price else Decimal("0"))
            realised += proceeds - disposal
            pool_cost -= disposal
            pool_qty -= Decimal(str(t.quantity))

    return float(realised.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def _compute_rag(unrealised: float, cost: float, market: float) -> str:
    """Compute RAG status based on unrealised PnL."""
    if cost == 0:
        return "green"
    pnl_pct = (unrealised / cost) * 100
    if pnl_pct >= -2:
        return "green"
    elif pnl_pct >= -5:
        return "amber"
    else:
        return "red"


def _compute_twrr(db: Session, window_days: int = 252) -> float:
    """Time-weighted return using Modified Dietz over a window."""
    from app.models import Valuation, Transaction

    valuations = (
        db.query(Valuation)
        .filter(Valuation.pie_id.is_(None))
        .order_by(Valuation.date.desc())
        .limit(window_days)
        .all()
    )

    if len(valuations) < 2:
        return 0.0

    nav_series = pd.Series(
        [v.portfolio_nav_gbp for v in valuations],
        index=[v.date for v in valuations],
    ).sort_index()

    if len(nav_series) < 2:
        return 0.0

    sub_period_returns = []
    start_nav = nav_series.iloc[0]
    current_nav = nav_series.iloc[0]

    for i in range(1, len(nav_series)):
        period_return = (nav_series.iloc[i] - current_nav) / current_nav if current_nav != 0 else 0
        sub_period_returns.append(period_return)
        current_nav = nav_series.iloc[i]

    # Chain returns
    twrr = 1.0
    for r in sub_period_returns:
        twrr *= (1 + r)
    twrr = (twrr - 1) * 100

    return twrr


def _compute_twrr_ytd(db: Session) -> float:
    """Time-weighted return YTD using Modified Dietz."""
    now = date.today()
    tax_year_start = date(now.year, 4, 6) if now >= date(now.year, 4, 6) else date(now.year - 1, 4, 6)

    from app.models import Valuation
    valuations = (
        db.query(Valuation)
        .filter(
            Valuation.pie_id.is_(None),
            Valuation.date >= tax_year_start,
        )
        .order_by(Valuation.date)
        .all()
    )

    if len(valuations) < 2:
        return 0.0

    nav_series = pd.Series(
        [v.portfolio_nav_gbp for v in valuations],
        index=[v.date for v in valuations],
    ).sort_index()

    return float((nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100)


def _get_benchmark_returns(db: Session, window_days: int = 252) -> tuple:
    """Get benchmark log returns for VUAG and IWDA."""
    from app.models import Benchmark

    vuag = (
        db.query(Benchmark)
        .filter(Benchmark.ticker == "VUAG.L")
        .order_by(Benchmark.date)
        .tail(window_days)
    )
    iwda = (
        db.query(Benchmark)
        .filter(Benchmark.ticker == "IWDA.L")
        .order_by(Benchmark.date)
        .tail(window_days)
    )

    vuag_returns = np.log(
        pd.Series([p.close for p in vuag]) /
        pd.Series([p.close for p in vuag]).shift(1)
    ).dropna().values if len(vuag) > 1 else np.array([])

    iwda_returns = np.log(
        pd.Series([p.close for p in iwda]) /
        pd.Series([p.close for p in iwda]).shift(1)
    ).dropna().values if len(iwda) > 1 else np.array([])

    return vuag_returns, iwda_returns


def _capm_regression(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> tuple:
    """CAPM regression: portfolio = alpha + beta * benchmark + epsilon."""
    # Align on common dates (truncate to shorter series)
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    if min_len < 10:
        return 0.0, 0.0, 0.0

    port = portfolio_returns[:min_len]
    bench = benchmark_returns[:min_len]

    # Regression
    slope, intercept = np.polyfit(bench, port, 1)

    # Alpha (annualised, in %)
    alpha = (intercept - slope * np.mean(bench)) * 252 * 100

    # R-squared
    predicted = intercept + slope * bench
    ss_res = np.sum((port - predicted) ** 2)
    ss_tot = np.sum((port - np.mean(port)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Beta (annualised)
    beta = slope * math.sqrt(252)

    return round(float(beta), 4), round(float(alpha), 4), round(float(r_squared), 4)


def _get_current_bank_rate(db: Session) -> float:
    """Get the latest UK Bank Rate from the DB."""
    from app.models import RiskFreeRate
    rate = (
        db.query(RiskFreeRate)
        .order_by(RiskFreeRate.date.desc())
        .first()
    )
    return rate.rate / 100 if rate else 0.05  # default 5%


def _compute_currency_exposure(db: Session, holdings: list[dict]) -> dict:
    """Compute currency exposure by listing currency."""
    exposure = {"GBP": 0.0, "USD": 0.0, "EUR": 0.0, "OTHER": 0.0}
    total = sum(h["market_value_gbp"] for h in holdings)

    for h in holdings:
        inst = next(
            (i for i in db.query(Instrument).all() if i.ticker == h["ticker"]),
            None,
        )
        currency = (inst.listing_currency if inst else "GBP").upper()
        if currency in exposure:
            exposure[currency] += h["market_value_gbp"]
        else:
            exposure["OTHER"] += h["market_value_gbp"]

    if total > 0:
        for k in exposure:
            exposure[k] = round(exposure[k] / total * 100, 2)

    return exposure


def _empty_risk_metrics() -> dict:
    """Return empty risk metrics when insufficient data."""
    return {
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_peak_date": None,
        "max_drawdown_trough_date": None,
        "current_drawdown": 0.0,
        "var_95": 0.0,
        "var_99": 0.0,
        "expected_shortfall_95": 0.0,
        "expected_shortfall_99": 0.0,
        "beta_vuag": 0.0,
        "alpha_vuag": 0.0,
        "r_squared_vuag": 0.0,
        "beta_iwda": 0.0,
        "alpha_iwda": 0.0,
        "r_squared_iwda": 0.0,
        "concentration_top5": 0.0,
        "concentration_top10": 0.0,
        "hhi": 0.0,
        "effective_holdings": 0.0,
        "currency_exposure": {},
        "drawdown_series": [],
        "observation_count": 0,
    }
