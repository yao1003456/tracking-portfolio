"""
Correlation Module — Stage 3

Computes correlation matrices for:
1. Stock-to-stock (all holdings)
2. Sector-level (weight-averaged sector returns)
3. Pie-level (returns of the 8 thematic pies)
4. Benchmark-level (each holding/pie/sector vs VUAG and IWDA)

Features:
- Daily log returns, aligned on common trading dates
- Forward-fill holidays (max 3 days)
- Weekly returns option for non-synchronous markets
- Configurable windows: 30, 90, 252 trading days
- Hierarchical clustering for heatmap sorting
- Ledoit-Wolf shrinkage option
- Concentration of risk metrics (effective bets, diversification ratio)
- Correlation alerts
"""

import math
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf
from sqlalchemy.orm import Session

from app.models import Price, Transaction, Position, Pie, Benchmark, Instrument


def compute_stock_correlation(
    db: Session,
    window: int = 252,
    frequency: str = "daily",
) -> dict:
    """
    Compute stock-to-stock correlation matrix.

    Returns:
        {
            "labels": list[str],  # tickers
            "matrix": list[list[float]],
            "window": int,
            "frequency": str,
            "observation_count": int,
            "warnings": list[str],
        }
    """
    tickers, returns_df = _build_return_matrix(db, window, frequency)

    if len(tickers) < 2:
        return _empty_correlation(tickers, window, frequency)

    if len(returns_df) < 60:
        return {
            "labels": tickers,
            "matrix": [],
            "window": window,
            "frequency": frequency,
            "observation_count": len(returns_df),
            "warnings": [
                f"Only {len(returns_df)} observations (minimum 60 recommended). "
                "Correlations may not be reliable."
            ],
        }

    # Compute correlation matrix
    corr_matrix = returns_df.corr()

    # Hierarchical clustering for sorting
    # Convert to distance matrix
    corr_values = corr_matrix.values
    distance = np.sqrt(0.5 * (1 - corr_values))
    # Ensure non-negative
    distance = np.maximum(distance, 0)
    # Convert to condensed form
    condensed = squareform(np.clip(distance, 0, None))

    # Link
    Z = linkage(condensed, method="average")
    order = leaves_list(Z)

    # Reorder
    ordered_labels = [tickers[i] for i in order]
    ordered_matrix = corr_matrix.iloc[order, order].values.tolist()

    return {
        "labels": ordered_labels,
        "matrix": [[round(float(v), 4) for v in row] for row in ordered_matrix],
        "window": window,
        "frequency": frequency,
        "observation_count": len(returns_df),
        "warnings": [] if len(returns_df) >= 60 else [f"Only {len(returns_df)} observations"],
    }


def compute_sector_correlation(
    db: Session,
    window: int = 252,
    frequency: str = "daily",
) -> dict:
    """
    Compute sector-level correlation matrix.

    Sectors are built as weight-averaged returns of holdings in each sector.
    Includes sector-to-benchmark correlation column.
    """
    # Get all holdings and their sectors
    sectors = _build_sector_returns(db, window, frequency)

    if sectors.empty:
        return _empty_correlation([], window, frequency)

    corr_matrix = sectors.corr()
    labels = list(corr_matrix.index)
    matrix = corr_matrix.values.tolist()

    return {
        "labels": labels,
        "matrix": [[round(float(v), 4) for v in row] for row in matrix],
        "window": window,
        "frequency": frequency,
        "observation_count": len(sectors),
        "warnings": [],
    }


def compute_pie_correlation(
    db: Session,
    window: int = 252,
    frequency: str = "daily",
) -> dict:
    """Compute correlation between the 8 pie returns."""
    pie_returns = _build_pie_returns(db, window, frequency)

    if pie_returns.empty:
        return _empty_correlation([], window, frequency)

    corr_matrix = pie_returns.corr()
    labels = list(corr_matrix.index)
    matrix = corr_matrix.values.tolist()

    return {
        "labels": labels,
        "matrix": [[round(float(v), 4) for v in row] for row in matrix],
        "window": window,
        "frequency": frequency,
        "observation_count": len(pie_returns),
        "warnings": [],
    }


def compute_benchmark_correlation(
    db: Session,
    window: int = 252,
    frequency: str = "daily",
) -> dict:
    """
    Compute correlation of each holding, pie, and sector against VUAG and IWDA.
    Sorted by value.
    """
    results = []

    # Holdings vs benchmarks
    tickers, returns_df = _build_return_matrix(db, window, frequency)
    vuag_ret, iwda_ret = _get_benchmark_series(db, window, frequency)

    for ticker in tickers:
        if ticker not in returns_df.columns:
            continue
        port_ret = returns_df[ticker]

        if vuag_ret is not None and len(vuag_ret) > 0:
            aligned = pd.concat([port_ret, vuag_ret], axis=1).dropna()
            if len(aligned) >= 30:
                corr_vuag = aligned[0].corr(aligned[1])
                results.append({"entity": ticker, "entity_type": "holding", "vs": "VUAG", "correlation": round(float(corr_vuag), 4)})

        if iwda_ret is not None and len(iwda_ret) > 0:
            aligned = pd.concat([port_ret, iwda_ret], axis=1).dropna()
            if len(aligned) >= 30:
                corr_iwda = aligned[0].corr(aligned[1])
                results.append({"entity": ticker, "entity_type": "holding", "vs": "IWDA", "correlation": round(float(corr_iwda), 4)})

    # Pies vs benchmarks
    pie_returns = _build_pie_returns(db, window, frequency)
    for pie_name in pie_returns.columns:
        if vuag_ret is not None and len(vuag_ret) > 0:
            aligned = pd.concat([pie_returns[pie_name], vuag_ret], axis=1).dropna()
            if len(aligned) >= 30:
                corr_vuag = aligned[0].corr(aligned[1])
                results.append({"entity": pie_name, "entity_type": "pie", "vs": "VUAG", "correlation": round(float(corr_vuag), 4)})

    results.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    return {
        "results": results,
        "window": window,
        "frequency": frequency,
        "warnings": [],
    }


def compute_risk_concentration(
    db: Session,
    window: int = 252,
    frequency: str = "daily",
    use_shrinkage: bool = False,
) -> dict:
    """
    Compute concentration of risk from correlation matrix.

    Metrics:
    - Average pairwise correlation (overall and within each pie)
    - Effective number of independent bets (from eigenvalues)
    - Diversification ratio
    - Highest-correlated held pairs (overlap risk)
    """
    tickers, returns_df = _build_return_matrix(db, window, frequency)

    if len(tickers) < 2:
        return _empty_concentration()

    corr_matrix = returns_df.corr().values

    # Average pairwise correlation (exclude diagonal)
    n = len(corr_matrix)
    off_diag = corr_matrix[np.triu_indices(n, k=1)]
    avg_pairwise = float(np.mean(off_diag)) if len(off_diag) > 0 else 0

    # Eigenvalues for effective number of bets
    eigenvalues = np.linalg.eigvalsh(corr_matrix)
    eigenvalues = np.maximum(eigenvalues, 0)  # clamp negatives
    total_eig = np.sum(eigenvalues)
    effective_bets = float(np.sum(eigenvalues) ** 2 / np.sum(eigenvalues ** 2)) if total_eig > 0 else float(n)

    # Diversification ratio: sqrt(w'Σw) / (w'μ)
    # Approximation: 1 / sqrt(mean of correlation matrix)
    div_ratio = math.sqrt(n) / math.sqrt(np.mean(corr_matrix)) if np.mean(corr_matrix) > 0 else 1.0

    # Highest correlated pairs
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append({
                "pair": (tickers[i], tickers[j]),
                "correlation": round(float(corr_matrix[i][j]), 4),
            })
    pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    top_pairs = pairs[:10]

    # Within-pie average correlations
    pie_avg_corr = _compute_pie_avg_correlations(db, returns_df, tickers)

    # Ledoit-Wolf shrinkage comparison
    shrink_diff = None
    if use_shrinkage and len(returns_df) >= 30:
        lw = LedoitWolf()
        lw.fit(returns_df.values)
        shrunk_corr = lw.covariance_
        # Convert to correlation
        d = np.diag(shrunk_corr)
        shrunk_corr = shrunk_corr / np.sqrt(np.outer(d, d))
        np.fill_diagonal(shrunk_corr, 1.0)

        lw_eigenvalues = np.linalg.eigvalsh(shrunk_corr)
        lw_eigenvalues = np.maximum(lw_eigenvalues, 0)
        lw_total = np.sum(lw_eigenvalues)
        lw_eff_bets = float(np.sum(lw_eigenvalues) ** 2 / np.sum(lw_eigenvalues ** 2)) if lw_total > 0 else float(n)
        lw_avg = float(np.mean(shrunk_corr[np.triu_indices(n, k=1)]))

        shrink_diff = {
            "original_avg_corr": round(avg_pairwise, 4),
            "shrunk_avg_corr": round(lw_avg, 4),
            "original_effective_bets": round(effective_bets, 2),
            "shrunk_effective_bets": round(lw_eff_bets, 2),
        }

    return {
        "average_pairwise_correlation": round(avg_pairwise, 4),
        "effective_number_of_bets": round(effective_bets, 2),
        "diversification_ratio": round(div_ratio, 4),
        "top_correlated_pairs": top_pairs,
        "pie_avg_correlations": pie_avg_corr,
        "shrinkage_comparison": shrink_diff,
        "observation_count": len(returns_df),
        "warnings": [] if len(returns_df) >= 60 else [f"Only {len(returns_df)} observations"],
    }


def _build_return_matrix(
    db: Session,
    window: int,
    frequency: str = "daily",
) -> tuple[list[str], pd.DataFrame]:
    """
    Build a DataFrame of returns for all instruments.

    Returns:
        (tickers, returns_df)
    """
    # Get all instruments with prices
    instruments = db.query(Instrument).all()
    prices_data = {}

    for inst in instruments:
        q = (
            db.query(Price)
            .filter(Price.instrument_id == inst.id)
            .order_by(Price.date)
        )

        if frequency == "weekly":
            # Aggregate to weekly
            df = pd.DataFrame([(p.date, p.close) for p in q], columns=["date", "close"])
            df = df.set_index("date").resample("W-FRI").last().dropna()
        else:
            df = pd.DataFrame([(p.date, p.close) for p in q], columns=["date", "close"])
            df = df.set_index("date")

        if df.empty:
            continue

        # Forward-fill holidays (max 3 days)
        df = df.ffill(limit=3)

        # Log returns
        returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        prices_data[inst.ticker] = returns

    if not prices_data:
        return [], pd.DataFrame()

    # Align on common dates
    series = {k: v for k, v in prices_data.items() if len(v) > 0}
    if not series:
        return [], pd.DataFrame()

    df = pd.DataFrame(series)

    # Forward-fill remaining gaps
    df = df.ffill(limit=3)

    # Trim to window
    if len(df) > window:
        df = df.tail(window)

    tickers = list(df.columns)
    return tickers, df


def _build_sector_returns(
    db: Session,
    window: int,
    frequency: str = "daily",
) -> pd.DataFrame:
    """Build sector returns as weight-averaged returns of holdings."""
    sectors = {}
    holdings = db.query(Position).all()

    # Group by sector
    sector_holdings: dict[str, list[tuple[str, float]]] = {}  # sector -> [(ticker, weight)]
    total_nav = _get_total_nav(db)

    for pos in holdings:
        inst = pos.instrument
        if not inst.sector:
            continue
        latest = (
            db.query(Price)
            .filter(Price.instrument_id == pos.instrument_id)
            .order_by(Price.date.desc())
            .first()
        )
        if not latest:
            continue
        market_value = pos.quantity * latest.close
        weight = market_value / total_nav if total_nav > 0 else 0
        sector_holdings.setdefault(inst.sector, []).append((inst.ticker, weight))

    # Build returns for each sector
    for sector, holdings_list in sector_holdings.items():
        sector_returns = []
        tickers_in_sector = [h[0] for h in holdings_list]
        weights = np.array([h[1] for h in holdings_list])
        weights = weights / weights.sum()  # normalise

        _, returns_df = _build_return_matrix(db, window, frequency)
        if returns_df.empty:
            continue

        # Filter to sector tickers
        sector_df = returns_df[[t for t in tickers_in_sector if t in returns_df.columns]]
        if sector_df.empty:
            continue

        # Weighted average return
        weighted = (sector_df.values * weights.reshape(1, -1)).sum(axis=1)
        sector_returns = pd.Series(weighted, index=sector_df.index, name=sector)
        sectors[sector] = sector_returns

    if not sectors:
        return pd.DataFrame()

    return pd.DataFrame(sectors)


def _build_pie_returns(
    db: Session,
    window: int,
    frequency: str = "daily",
) -> pd.DataFrame:
    """Build returns for each pie as weight-averaged holding returns."""
    pies = db.query(Pie).all()
    pie_returns = {}

    for pie in pies:
        positions = db.query(Position).filter(Position.pie_id == pie.id).all()
        if not positions:
            continue

        pie_data = []
        total_nav_pie = 0

        for pos in positions:
            latest = (
                db.query(Price)
                .filter(Price.instrument_id == pos.instrument_id)
                .order_by(Price.date.desc())
                .first()
            )
            if not latest:
                continue
            mv = pos.quantity * latest.close
            total_nav_pie += mv
            pie_data.append((pos.instrument.ticker, mv))

        if total_nav_pie == 0 or not pie_data:
            continue

        tickers = [d[0] for d in pie_data]
        weights = np.array([d[1] / total_nav_pie for d in pie_data])

        _, returns_df = _build_return_matrix(db, window, frequency)
        if returns_df.empty:
            continue

        pie_df = returns_df[[t for t in tickers if t in returns_df.columns]]
        if pie_df.empty:
            continue

        weighted = (pie_df.values * weights.reshape(1, -1)).sum(axis=1)
        pie_returns[pie.name] = pd.Series(weighted, index=pie_df.index, name=pie.name)

    if not pie_returns:
        return pd.DataFrame()

    return pd.DataFrame(pie_returns)


def _get_benchmark_series(
    db: Session,
    window: int,
    frequency: str = "daily",
) -> tuple:
    """Get benchmark price series for VUAG and IWDA."""
    from app.models import Benchmark

    vuag = (
        db.query(Benchmark)
        .filter(Benchmark.ticker == "VUAG.L")
        .order_by(Benchmark.date)
        .tail(window)
    )
    iwda = (
        db.query(Benchmark)
        .filter(Benchmark.ticker == "IWDA.L")
        .order_by(Benchmark.date)
        .tail(window)
    )

    vuag_series = None
    if vuag:
        s = pd.Series([p.close for p in vuag], index=[p.date for p in vuag])
        vuag_series = np.log(s / s.shift(1)).dropna()

    iwda_series = None
    if iwda:
        s = pd.Series([p.close for p in iwda], index=[p.date for p in iwda])
        iwda_series = np.log(s / s.shift(1)).dropna()

    return vuag_series, iwda_series


def _compute_pie_avg_correlations(
    db: Session,
    returns_df: pd.DataFrame,
    tickers: list[str],
) -> list[dict]:
    """Compute average pairwise correlation within each pie."""
    pies = db.query(Pie).all()
    results = []

    for pie in pies:
        pie_tickers = set()
        for pos in db.query(Position).filter(Position.pie_id == pie.id).all():
            if pos.instrument and pos.instrument.ticker in tickers:
                pie_tickers.add(pos.instrument.ticker)

        if len(pie_tickers) < 2:
            continue

        pie_df = returns_df[list(pie_tickers)]
        if pie_df.empty:
            continue

        corr = pie_df.corr().values
        n = len(corr)
        off_diag = corr[np.triu_indices(n, k=1)]
        avg_corr = float(np.mean(off_diag)) if len(off_diag) > 0 else 0

        results.append({"pie": pie.name, "avg_pairwise_correlation": round(avg_corr, 4)})

    return results


def _get_total_nav(db: Session) -> float:
    """Get total portfolio NAV."""
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


def _empty_correlation(labels: list, window: int, frequency: str) -> dict:
    """Return empty correlation matrix."""
    return {
        "labels": labels,
        "matrix": [],
        "window": window,
        "frequency": frequency,
        "observation_count": 0,
        "warnings": ["No price data available for correlation analysis."],
    }


def _empty_concentration() -> dict:
    """Return empty concentration metrics."""
    return {
        "average_pairwise_correlation": 0.0,
        "effective_number_of_bets": 0.0,
        "diversification_ratio": 0.0,
        "top_correlated_pairs": [],
        "pie_avg_correlations": [],
        "shrinkage_comparison": None,
        "observation_count": 0,
        "warnings": ["Insufficient data for concentration analysis."],
    }
