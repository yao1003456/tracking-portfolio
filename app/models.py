"""SQLAlchemy ORM models for Great Dyke Meridian."""

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    JSON,
    Enum,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ── Enums ───────────────────────────────────────────────────────────────────

class AssetClass(str, enum.Enum):
    STOCK = "stock"
    ETF = "etf"
    FUND = "fund"
    CASH = "cash"


class TransactionType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    FX = "fx"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"


class PieStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    WATCH = "watch"


class RAGStatus(str, enum.Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


# ── Models ──────────────────────────────────────────────────────────────────

class Instrument(Base):
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    listing_currency = Column(String(3), nullable=False, default="GBP")
    exchange = Column(String(50), nullable=True)
    asset_class = Column(Enum(AssetClass), nullable=False, default=AssetClass.STOCK)
    sector = Column(String(100), nullable=True)
    country = Column(String(50), nullable=True)
    isin = Column(String(12), nullable=True)
    yfinance_symbol = Column(String(30), nullable=True)  # mapped symbol

    positions = relationship("Position", back_populates="instrument")
    transactions = relationship("Transaction", back_populates="instrument")
    prices = relationship("Price", back_populates="instrument")

    def __repr__(self):
        return f"<Instrument {self.ticker}>"


class Pie(Base):
    __tablename__ = "pies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    target_allocation = Column(Float, nullable=False)  # percentage
    status = Column(Enum(PieStatus), nullable=False, default=PieStatus.ACTIVE)
    notes = Column(Text, nullable=True)

    positions = relationship("Position", back_populates="pie")

    def __repr__(self):
        return f"<Pie {self.name}>"


class Position(Base):
    """A holding within a pie."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pie_id = Column(Integer, ForeignKey("pies.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    last_updated = Column(DateTime, default=datetime.now(timezone.utc))

    pie = relationship("Pie", back_populates="positions")
    instrument = relationship("Instrument", back_populates="positions")

    __table_args__ = (
        UniqueConstraint("pie_id", "instrument_id", name="uq_pie_instrument"),
    )

    def __repr__(self):
        return f"<Position pie={self.pie_id} inst={self.instrument_id} qty={self.quantity}>"


class Transaction(Base):
    """Every financial event: buy, sell, dividend, fee, FX, deposit, withdrawal."""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    type = Column(Enum(TransactionType), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=True)
    pie_id = Column(Integer, ForeignKey("pies.id"), nullable=True)
    quantity = Column(Float, nullable=False, default=0)
    price = Column(Float, nullable=True)  # per-share price
    currency = Column(String(3), nullable=True)
    amount_gbp = Column(Float, nullable=True)  # converted to GBP
    fee_gbp = Column(Float, nullable=False, default=0)
    fx_rate = Column(Float, nullable=True)  # rate used for conversion
    source = Column(String(50), nullable=False, default="manual")  # excel_migration, trading212, manual
    external_id = Column(String(100), nullable=True)  # Trading 212 transaction ID
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    instrument = relationship("Instrument", back_populates="transactions")
    pie = relationship("Pie", back_populates=None)

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_external_id"),
    )

    def __repr__(self):
        return f"<Transaction {self.type} {self.date} {self.source}>"


class Price(Base):
    """Daily close price per instrument."""
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False)
    close = Column(Float, nullable=False)
    source = Column(String(20), nullable=False, default="yfinance")
    fetched_at = Column(DateTime, nullable=True)

    instrument = relationship("Instrument", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_instrument_date"),
    )

    def __repr__(self):
        return f"<Price {self.instrument_id} {self.date} {self.close}>"


class FXRate(Base):
    """Daily GBP cross rate."""
    __tablename__ = "fx_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    currency = Column(String(3), nullable=False)  # e.g. USD, EUR
    rate = Column(Float, nullable=False)  # 1 unit of currency = X GBP
    source = Column(String(20), nullable=False, default="yfinance")

    __table_args__ = (
        UniqueConstraint("date", "currency", name="uq_date_currency"),
    )

    def __repr__(self):
        return f"<FXRate {self.currency} {self.date} {self.rate}>"


class Benchmark(Base):
    """Benchmark daily prices (VUAG, IWDA)."""
    __tablename__ = "benchmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    close = Column(Float, nullable=False)
    source = Column(String(20), nullable=False, default="yfinance")

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_benchmark_ticker_date"),
    )

    def __repr__(self):
        return f"<Benchmark {self.ticker} {self.date}>"


class RiskFreeRate(Base):
    """UK Bank Rate, dated and editable."""
    __tablename__ = "risk_free_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    rate = Column(Float, nullable=False)  # annual percentage

    def __repr__(self):
        return f"<RiskFreeRate {self.date} {self.rate}%"


class Valuation(Base):
    """Daily NAV snapshot — per portfolio, per pie, per holding."""
    __tablename__ = "valuations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    portfolio_nav_gbp = Column(Float, nullable=False)
    pie_id = Column(Integer, ForeignKey("pies.id"), nullable=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=True)
    holding_value_gbp = Column(Float, nullable=True)
    source = Column(String(50), nullable=False, default="calculation")

    pie = relationship("Pie")
    instrument = relationship("Instrument")

    __table_args__ = (
        UniqueConstraint("date", "pie_id", "instrument_id", name="uq_valuation"),
    )

    def __repr__(self):
        return f"<Valuation {self.date} nav={self.portfolio_nav_gbp}>"


class ThesisNote(Base):
    """Dated free text per instrument or pie."""
    __tablename__ = "thesis_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=True)
    pie_id = Column(Integer, ForeignKey("pies.id"), nullable=True)
    text = Column(Text, nullable=False)
    review_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ThesisNote {self.date}>"


class Alert(Base):
    """Configurable alert rules and triggers."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule = Column(String(100), nullable=False)
    threshold = Column(Float, nullable=True)
    triggered_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    message = Column(Text, nullable=True)
    entity_type = Column(String(20), nullable=True)  # pie, holding, portfolio
    entity_id = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<Alert {self.rule} triggered={self.triggered_at}>"


class Setting(Base):
    """All configurable values."""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(JSON, nullable=False)

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"


class AuditLog(Base):
    """Append-only audit trail."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    actor = Column(String(50), nullable=True)  # user or "system"
    action = Column(String(50), nullable=False)  # login, import, create, update, delete
    entity = Column(String(50), nullable=True)  # transaction, price, etc.
    entity_id = Column(Integer, nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    source_file_hash = Column(String(64), nullable=True)  # SHA-256 of imported file

    def __repr__(self):
        return f"<AuditLog {self.action} {self.timestamp}>"
