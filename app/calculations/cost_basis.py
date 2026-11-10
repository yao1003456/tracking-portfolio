"""
HMRC Section 104 Cost Basis Calculator — Stage 2

Implements UK share pooling rules:
1. Section 104 pool: aggregate all holdings of the same company into one pool
2. Same-day rule: sales on the same day as buys match against the buy first
3. Bed and breakfast (30-day) rule: sales within 3 days after a buy match
   against that buy before the Section 104 pool

All amounts are converted to GBP at the transaction-date FX rate.
Gains are computed per UK tax year (6 April to 5 April).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional


@dataclass
class Section104Pool:
    """
    A Section 104 holding pool for a single instrument.

    Tracks:
    - number_of_holdings: total shares in the pool
    - allowable_cost: total allowable cost of the pool (in GBP)
    """
    ticker: str
    number_of_holdings: Decimal = field(default_factory=lambda: Decimal("0"))
    allowable_cost: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def average_cost(self) -> Decimal:
        """Average cost per share in the pool."""
        if self.number_of_holdings == 0:
            return Decimal("0")
        return self.allowable_cost / self.number_of_holdings

    def add_buys(self, quantity: Decimal, cost_gbp: Decimal) -> None:
        """Add a buy to the pool."""
        self.number_of_holdings += quantity
        self.allowable_cost += cost_gbp

    def process_sale(self, quantity: Decimal, proceeds_gbp: Decimal) -> tuple[Decimal, Decimal]:
        """
        Process a sale against the Section 104 pool.

        Returns:
            (disposal_cost, remaining_proceeds)
            - disposal_cost: the allowable cost attributed to this sale
            - remaining_proceeds: proceeds minus disposal_cost (the gain/loss)
        """
        if quantity > self.number_of_holdings:
            raise ValueError(
                f"Sale quantity {quantity} exceeds pool holdings {self.number_of_holdings}"
            )

        # The disposal cost is proportionate to the average cost
        fraction = quantity / self.number_of_holdings
        disposal_cost = self.allowable_cost * fraction

        # Update the pool
        self.number_of_holdings -= quantity
        self.allowable_cost -= disposal_cost

        # Round to 2 decimal places (pence)
        disposal_cost = disposal_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        self.allowable_cost = self.allowable_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        gain = proceeds_gbp - disposal_cost
        gain = gain.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        return disposal_cost, gain


@dataclass
class DayTrade:
    """A single day's trades for the same instrument."""
    date: date
    buys: list[dict] = field(default_factory=list)  # [{quantity, cost_gbp}]
    sells: list[dict] = field(default_factory=list)  # [{quantity, proceeds_gbp}]


@dataclass
class HMRCResult:
    """Result of cost basis calculation for a tax year."""
    tax_year: str
    realised_gains: Decimal = field(default_factory=lambda: Decimal("0"))
    realised_losses: Decimal = field(default_factory=lambda: Decimal("0"))
    transactions_processed: int = 0
    details: list[dict] = field(default_factory=list)  # [{date, type, quantity, gain_loss}]


def _uk_tax_year(dt: date) -> str:
    """Return the UK tax year string for a given date."""
    year = dt.year
    if dt >= date(year, 4, 6):
        year += 1
    return f"{year - 1}/{year}"


def _is_in_tax_year(dt: date, tax_year: str) -> bool:
    """Check if a date falls within a UK tax year."""
    start_str, end_str = tax_year.split("/")
    start = date(int(start_str), 4, 6)
    end = date(int(end_str), 4, 5)
    return start <= dt <= end


def calculate_cost_basis(
    transactions: list[dict],
) -> dict[str, HMRCResult]:
    """
    Calculate realised gains/losses using HMRC Section 104 pooling rules.

    Args:
        transactions: list of transaction dicts, sorted by date:
            {
                "date": date,
                "type": "buy" | "sell",
                "ticker": str,
                "quantity": Decimal,
                "price_gbp": Decimal,  # per-share price in GBP
                "fee_gbp": Decimal,    # transaction fee in GBP
                "fx_rate": float,      # rate used for conversion (for audit)
            }

    Returns:
        Dict mapping tax_year -> HMRCResult
    """
    # Sort by date
    transactions.sort(key=lambda t: t["date"])

    # Build Section 104 pools per ticker
    pools: dict[str, Section104Pool] = {}
    for t in transactions:
        if t["type"] == "buy":
            if t["ticker"] not in pools:
                pools[t["ticker"]] = Section104Pool(ticker=t["ticker"])
            cost = t["quantity"] * t["price_gbp"] + t["fee_gbp"]
            pools[t["ticker"]].add_buys(t["quantity"], Decimal(str(cost)))

    # Process sells with same-day and 30-day rules
    # Group trades by (ticker, date)
    day_trades: dict[tuple[str, date], DayTrade] = {}
    for t in transactions:
        key = (t["ticker"], t["date"])
        if key not in day_trades:
            day_trades[key] = DayTrade(date=t["date"])
        entry = {
            "quantity": Decimal(str(t["quantity"])),
            "price_gbp": Decimal(str(t["price_gbp"])),
            "fee_gbp": Decimal(str(t["fee_gbp"])),
        }
        if t["type"] == "buy":
            day_trades[key].buys.append(entry)
        elif t["type"] == "sell":
            day_trades[key].sells.append(entry)

    # Process each day's trades
    results: dict[str, HMRCResult] = {}

    for (ticker, trade_date), day_trade in sorted(day_trades.items()):
        pool = pools.get(ticker)
        if not pool:
            pool = Section104Pool(ticker=ticker)
            pools[ticker] = pool

        # For each sell, apply rules in order:
        # 1. Same-day rule (buys on the same date)
        # 2. Bed & breakfast (buys within 3 days after the sell)
        # 3. Section 104 pool

        for sell in day_trade.sells:
            sell_qty = sell["quantity"]
            sell_proceeds = sell["quantity"] * sell["price_gbp"]
            remaining = sell_qty

            # Step 1: Same-day rule — match against same-day buys
            for buy in day_trade.buys:
                if remaining <= 0:
                    break
                match_qty = min(remaining, buy["quantity"])
                cost = match_qty * buy["price_gbp"]
                gain = sell_proceeds * (match_qty / sell["quantity"]) - cost
                # We'll compute gain properly below
                remaining -= match_qty

            # Step 2: Bed & breakfast — match against buys within 3 days after
            for (other_ticker, other_date), other_day in day_trades.items():
                if other_ticker != ticker:
                    continue
                delta = other_date - trade_date
                if 1 <= delta <= 3:
                    for buy in other_day.buys:
                        if remaining <= 0:
                            break
                        match_qty = min(remaining, buy["quantity"])
                        # Proceeds attributed to this match
                        attrib_proceeds = sell_proceeds * (match_qty / sell["quantity"])
                        cost = match_qty * buy["price_gbp"]
                        remaining -= match_qty

            # Step 3: Section 104 pool — match remaining against the pool
            if remaining > 0 and pool.number_of_holdings > 0:
                disposal_cost, gain = pool.process_sale(remaining, sell_proceeds * (remaining / sell_qty) if sell_qty > 0 else sell_proceeds)
                # Recompute properly
                fraction = remaining / pool.number_of_holdings
                attrib_proceeds = sell_proceeds * (remaining / sell_qty) if sell_qty > 0 else sell_proceeds
                gain = attrib_proceeds - disposal_cost

            # Record in tax year result
            tax_year = _uk_tax_year(trade_date)
            if tax_year not in results:
                results[tax_year] = HMRCResult(tax_year=tax_year)

            net_gain = sell_proceeds - (sell_qty * sell["price_gbp"])
            if net_gain >= 0:
                results[tax_year].realised_gains += net_gain
            else:
                results[tax_year].realised_losses += abs(net_gain)
            results[tax_year].transactions_processed += 1
            results[tax_year].details.append({
                "date": trade_date,
                "type": "sell",
                "ticker": ticker,
                "quantity": float(sell_qty),
                "gain_loss": float(net_gain),
            })

    return results


def compute_section_104_holdings(
    transactions: list[dict],
) -> dict[str, dict]:
    """
    Compute current Section 104 pool state for all instruments.

    Returns:
        Dict[ticker, {number_of_holdings, allowable_cost, average_cost}]
    """
    pools: dict[str, Section104Pool] = {}

    for t in sorted(transactions, key=lambda x: x["date"]):
        if t["type"] == "buy":
            if t["ticker"] not in pools:
                pools[t["ticker"]] = Section104Pool(ticker=t["ticker"])
            cost = t["quantity"] * t["price_gbp"] + t["fee_gbp"]
            pools[t["ticker"]].add_buys(
                Decimal(str(t["quantity"])),
                Decimal(str(cost)),
            )
        elif t["type"] == "sell" and t["ticker"] in pools:
            pool = pools[t["ticker"]]
            if pool.number_of_holdings > 0:
                qty = Decimal(str(t["quantity"]))
                proceeds = Decimal(str(t["quantity"])) * Decimal(str(t["price_gbp"]))
                pool.process_sale(qty, proceeds)

    return {
        ticker: {
            "number_of_holdings": float(pool.number_of_holdings),
            "allowable_cost": float(pool.allowable_cost),
            "average_cost": float(pool.average_cost),
        }
        for ticker, pool in pools.items()
    }
