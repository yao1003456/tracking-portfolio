"""
Price and FX Data Adapter — Stage 2

Interface for fetching market data via yfinance (free).
Abstracted so a paid provider can be swapped in later without
changing calculation code.
"""

import hashlib
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from app.models import Price, FXRate, Benchmark
from app.config import settings

logger = logging.getLogger(__name__)


class PriceAdapter:
    """
    Adapter interface for market data.

    Default implementation uses yfinance.
    A paid provider can replace this by subclassing and overriding methods.
    """

    def fetch_price(self, ticker: str, start: date, end: date) -> list[dict]:
        """
        Fetch daily prices for a ticker.

        Returns:
            list of {"date": date, "close": float}
        """
        try:
            ticker_obj = yf.Ticker(ticker)
            df = ticker_obj.history(start=start, end=end, auto_adjust=False)

            if df.empty:
                logger.warning(f"No price data for {ticker} between {start} and {end}")
                return []

            return [
                {"date": dt.date(), "close": float(row["Close"])}
                for dt, row in df.iterrows()
            ]
        except Exception as e:
            logger.error(f"Failed to fetch price for {ticker}: {e}")
            return []

    def fetch_bulk(self, tickers: list[str], start: date, end: date) -> dict[str, list[dict]]:
        """
        Fetch prices for multiple tickers in bulk.

        Returns:
            dict[ticker, list[{"date", "close"}]]
        """
        result = {}
        for ticker in tickers:
            result[ticker] = self.fetch_price(ticker, start, end)
        return result

    def save_prices(self, db: Session, ticker: str, prices: list[dict]) -> int:
        """
        Save prices to the database, upserting existing records.

        Returns:
            number of new/updated records
        """
        inst = db.query(
            db.query(Instrument).filter(Instrument.ticker == ticker).first()
        ) if False else None

        # Find the instrument
        from app.models import Instrument
        inst = db.query(Instrument).filter(Instrument.ticker == ticker).first()
        if not inst:
            logger.warning(f"No instrument found for ticker {ticker}. Skipping price save.")
            return 0

        count = 0
        for p in prices:
            existing = (
                db.query(Price)
                .filter(
                    Price.instrument_id == inst.id,
                    Price.date == p["date"],
                )
                .first()
            )
            if existing:
                existing.close = p["close"]
                existing.fetched_at = datetime.now(timezone.utc)
            else:
                db.add(Price(
                    instrument_id=inst.id,
                    date=p["date"],
                    close=p["close"],
                    source="yfinance",
                    fetched_at=datetime.now(timezone.utc),
                ))
                count += 1

        db.commit()
        return count


class FXAdapter:
    """Adapter for FX rate data."""

    def fetch_fx_rates(self, currencies: list[str], start: date, end: date) -> list[dict]:
        """
        Fetch daily GBP cross rates.

        Returns:
            list of {"date": date, "currency": str, "rate": float}
            where rate = 1 unit of currency in GBP
        """
        rates = []
        for curr in currencies:
            if curr == "GBP":
                continue  # GBP/GBP = 1.0

            # Use yfinance for currency pairs
            # GBPUSD = 1 USD in GBP, so we need 1/GBPUSD for USD/GBP
            pair = f"GBP{curr}=X"
            try:
                ticker_obj = yf.Ticker(pair)
                df = ticker_obj.history(start=start, end=end, auto_adjust=False)

                if df.empty:
                    logger.warning(f"No FX data for {pair}")
                    continue

                for dt, row in df.iterrows():
                    # yfinance gives us the close price
                    # For GBPUSD=X, this is how many USD per 1 GBP
                    # We want GBP per 1 unit of currency
                    if curr in ("USD", "EUR", "JPY", "CHF", "AUD", "CAD"):
                        # The pair is GBP{CUR}=X, so close = 1 CUR in GBP
                        rates.append({
                            "date": dt.date(),
                            "currency": curr,
                            "rate": float(row["Close"]),
                        })
            except Exception as e:
                logger.error(f"Failed to fetch FX for {curr}: {e}")

        return rates

    def save_fx_rates(self, db: Session, rates: list[dict]) -> int:
        """Save FX rates to DB, upserting existing."""
        count = 0
        for r in rates:
            existing = (
                db.query(FXRate)
                .filter(
                    FXRate.date == r["date"],
                    FXRate.currency == r["currency"],
                )
                .first()
            )
            if existing:
                existing.rate = r["rate"]
            else:
                db.add(FXRate(
                    date=r["date"],
                    currency=r["currency"],
                    rate=r["rate"],
                    source="yfinance",
                ))
                count += 1

        db.commit()
        return count


def refresh_prices(db: Session, days_back: int = 5) -> dict:
    """
    Refresh price data for all instruments.

    Args:
        db: database session
        days_back: how many days back to fetch (default 5 trading days)

    Returns:
        summary dict with counts per ticker
    """
    from app.models import Instrument

    instruments = db.query(Instrument).all()
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back * 2)  # buffer for weekends

    adapter = PriceAdapter()
    results = {}

    for inst in instruments:
        yf_symbol = inst.yfinance_symbol or inst.ticker
        prices = adapter.fetch_price(yf_symbol, start_date, end_date)
        if prices:
            count = adapter.save_prices(db, inst.ticker, prices)
            results[inst.ticker] = count

    return results


def refresh_fx_rates(db: Session, currencies: list[str] = None, days_back: int = 5) -> dict:
    """
    Refresh FX rates.

    Returns:
        summary dict with counts per currency
    """
    from app.models import FXRate

    if currencies is None:
        # Detect currencies from holdings
        currencies = ["USD", "EUR", "JPY", "CHF"]

    adapter = FXAdapter()
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back * 2)

    results = {}
    rates = adapter.fetch_fx_rates(currencies, start_date, end_date)
    count = adapter.save_fx_rates(db, rates)

    for curr in currencies:
        results[curr] = count

    return results


def check_price_freshness(db: Session) -> list[dict]:
    """
    Check if any price data is stale (> 1 trading day old).

    Returns:
        list of warnings for stale prices
    """
    from app.models import Instrument, Price

    warnings = []
    instruments = db.query(Instrument).all()

    for inst in instruments:
        latest = (
            db.query(Price)
            .filter(Price.instrument_id == inst.id)
            .order_by(Price.date.desc())
            .first()
        )
        if latest:
            days_ago = (date.today() - latest.date).days
            if days_ago > 2:  # > 1 trading day (approx 2 calendar days)
                warnings.append({
                    "ticker": inst.ticker,
                    "last_date": latest.date.isoformat(),
                    "days_ago": days_ago,
                    "message": f"Price for {inst.ticker} is {days_ago} days old",
                })

    return warnings
