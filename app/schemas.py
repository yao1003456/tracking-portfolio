"""Pydantic schemas for API validation."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Instrument ──────────────────────────────────────────────────────────────

class InstrumentCreate(BaseModel):
    ticker: str
    name: str
    listing_currency: str = "GBP"
    exchange: Optional[str] = None
    asset_class: str = "stock"
    sector: Optional[str] = None
    country: Optional[str] = None
    isin: Optional[str] = None
    yfinance_symbol: Optional[str] = None


class InstrumentRead(InstrumentCreate):
    id: int
    model_config = {"from_orm": True}


# ── Pie ─────────────────────────────────────────────────────────────────────

class PieCreate(BaseModel):
    name: str
    target_allocation: float
    status: str = "active"
    notes: Optional[str] = None


class PieRead(PieCreate):
    id: int
    model_config = {"from_orm": True}


# ── Position ────────────────────────────────────────────────────────────────

class PositionCreate(BaseModel):
    pie_id: int
    instrument_id: int
    quantity: float


class PositionRead(PositionCreate):
    id: int
    last_updated: Optional[datetime] = None
    model_config = {"from_orm": True}


# ── Transaction ─────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    date: date
    type: str
    instrument_id: Optional[int] = None
    pie_id: Optional[int] = None
    quantity: float
    price: Optional[float] = None
    currency: Optional[str] = None
    amount_gbp: Optional[float] = None
    fee_gbp: float = 0
    fx_rate: Optional[float] = None
    source: str = "manual"
    external_id: Optional[str] = None
    notes: Optional[str] = None


class TransactionRead(TransactionCreate):
    id: int
    created_at: Optional[datetime] = None
    model_config = {"from_orm": True}


# ── Price ───────────────────────────────────────────────────────────────────

class PriceCreate(BaseModel):
    instrument_id: int
    date: date
    close: float
    source: str = "yfinance"


class PriceRead(PriceCreate):
    id: int
    fetched_at: Optional[datetime] = None
    model_config = {"from_orm": True}


# ── Valuation ───────────────────────────────────────────────────────────────

class ValuationCreate(BaseModel):
    date: date
    portfolio_nav_gbp: float
    pie_id: Optional[int] = None
    instrument_id: Optional[int] = None
    holding_value_gbp: Optional[float] = None
    source: str = "calculation"


class ValuationRead(ValuationCreate):
    id: int
    model_config = {"from_orm": True}


# ── Alert ───────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    rule: str
    threshold: Optional[float] = None
    message: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None


class AlertRead(AlertCreate):
    id: int
    triggered_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    model_config = {"from_orm": True}


# ── Setting ─────────────────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    value: dict


# ── AuditLog ────────────────────────────────────────────────────────────────

class AuditLogRead(BaseModel):
    id: int
    timestamp: datetime
    actor: Optional[str] = None
    action: str
    entity: Optional[str] = None
    entity_id: Optional[int] = None
    before: Optional[dict] = None
    after: Optional[dict] = None
    source_file_hash: Optional[str] = None
    model_config = {"from_orm": True}


# ── AXIS Summary ────────────────────────────────────────────────────────────

class AxisSummary(BaseModel):
    nav_gbp: float
    day_return: float
    mtd_return: float
    ytd_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_peak_date: Optional[date] = None
    max_drawdown_trough_date: Optional[date] = None
    avg_pairwise_correlation: float
    effective_number_of_bets: float
    data_freshness: dict
    alerts_count: int
    next_alert: Optional[str] = None


# ── Holdings Table Row ──────────────────────────────────────────────────────

class HoldingsRow(BaseModel):
    ticker: str
    name: str
    pie: str
    quantity: float
    section_104_cost: float
    current_price: float
    market_value_gbp: float
    weight: float
    unrealised_pnl_gbp: float
    realised_pnl_gbp: float
    dividends_gbp: float
    rag: str
    last_price_date: Optional[date] = None


# ── Risk Summary ────────────────────────────────────────────────────────────

class RiskSummary(BaseModel):
    var_95: float
    var_99: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    beta_vuag: float
    alpha_vuag: float
    r_squared_vuag: float
    beta_iwda: float
    alpha_iwda: float
    r_squared_iwda: float
    concentration_top5: float
    concentration_top10: float
    hhi: float
    effective_holdings: float
    currency_exposure: dict
    drawdown_series: list  # [{date, drawdown}]


# ── Correlation Matrix ──────────────────────────────────────────────────────

class CorrelationMatrix(BaseModel):
    labels: list[str]
    matrix: list[list[float]]
    window: int  # trading days
    frequency: str  # daily or weekly
    observation_count: int
    warnings: list[str] = []


# ── Attribution ─────────────────────────────────────────────────────────────

class AttributionSummary(BaseModel):
    total_return: float
    market_component: float
    alpha_component: float
    by_pie: list[dict]
    by_sector: list[dict]
    by_holding: list[dict]
    win_loss_ratio: float
    profit_factor: float
    avg_holding_period_days: float
    realised_gains_by_tax_year: list[dict]


# ── Projection ──────────────────────────────────────────────────────────────

class ProjectionScenario(BaseModel):
    name: str
    annual_return: float  # expected annual return %
    annual_volatility: float  # expected annual vol %


class ProjectionInput(BaseModel):
    current_nav: float
    monthly_contribution: float
    target_date: date
    scenarios: list[ProjectionScenario]


class ProjectionResult(BaseModel):
    scenario_name: str
    monthly_values: list[dict]  # [{date, value}]
    final_value: float
    total_contributed: float
    total_gain: float


# ── Tax Summary ─────────────────────────────────────────────────────────────

class TaxSummary(BaseModel):
    tax_year: str
    realised_gains: float
    realised_losses: float
    net_gains: float
    annual_exempt: float
    taxable_gains: float
    dividend_income: float
    dividend_allowance: float
    taxable_dividends: float
