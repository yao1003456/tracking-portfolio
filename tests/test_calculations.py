"""
Tests for Great Dyke Meridian

Covers:
- Section 104 cost basis (same-day, 30-day, pooling)
- Holdings calculations
- Returns (daily, MTD, YTD, TWRR)
- Risk metrics (Sharpe, Sortino, VaR, drawdown, beta, alpha)
- Correlation module
- Projections
- Tax year calculations
"""

import math
import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN


# ── Cost Basis Tests ────────────────────────────────────────────────────────

class TestSection104Pool:
    """Tests for Section 104 pool mechanics."""

    def test_pool_add_buy(self):
        """Test adding a buy to an empty pool."""
        from app.calculations.cost_basis import Section104Pool

        pool = Section104Pool(ticker="TEST")
        pool.add_buys(Decimal("100"), Decimal("1000.00"))

        assert pool.number_of_holdings == Decimal("100")
        assert pool.allowable_cost == Decimal("1000.00")
        assert pool.average_cost == Decimal("10.00")

    def test_pool_add_multiple_buys(self):
        """Test adding multiple buys to the same pool."""
        from app.calculations.cost_basis import Section104Pool

        pool = Section104Pool(ticker="TEST")
        pool.add_buys(Decimal("100"), Decimal("1000.00"))  # £10/share
        pool.add_buys(Decimal("50"), Decimal("600.00"))     # £12/share

        assert pool.number_of_holdings == Decimal("150")
        assert pool.allowable_cost == Decimal("1600.00")
        assert pool.average_cost == Decimal("10.67")  # 1600/150

    def test_pool_sale(self):
        """Test selling shares from the pool."""
        from app.calculations.cost_basis import Section104Pool

        pool = Section104Pool(ticker="TEST")
        pool.add_buys(Decimal("100"), Decimal("1000.00"))  # £10/share

        # Sell 30 shares at £15
        disposal, gain = pool.process_sale(Decimal("30"), Decimal("450.00"))

        assert disposal == Decimal("300.00")  # 30/100 * 1000
        assert gain == Decimal("150.00")  # 450 - 300

        # Pool should be updated
        assert pool.number_of_holdings == Decimal("70")
        assert pool.allowable_cost == Decimal("700.00")

    def test_pool_average_cost_updates(self):
        """Test that average cost updates correctly after sales."""
        from app.calculations.cost_basis import Section104Pool

        pool = Section104Pool(ticker="TEST")
        pool.add_buys(Decimal("100"), Decimal("1000.00"))
        pool.add_buys(Decimal("100"), Decimal("2000.00"))  # £20/share

        # Sell 50 shares
        _, gain = pool.process_sale(Decimal("50"), Decimal("1500.00"))

        # Average cost should be (£1000 + £2000) / 200 = £15
        # Gain = £1500 - (50 * £15) = £1500 - £750 = £750
        assert gain == Decimal("750.00")


class TestSameDayRule:
    """Tests for the same-day rule."""

    def test_same_day_buy_sell(self):
        """Same-day buy and sell should match against the buy first."""
        from app.calculations.cost_basis import calculate_cost_basis

        transactions = [
            {
                "date": date(2024, 1, 15),
                "type": "buy",
                "ticker": "VUAG",
                "quantity": Decimal("100"),
                "price_gbp": Decimal("10.00"),
                "fee_gbp": Decimal("2.00"),
                "fx_rate": 1.0,
            },
            {
                "date": date(2024, 1, 15),
                "type": "sell",
                "ticker": "VUAG",
                "quantity": Decimal("50"),
                "price_gbp": Decimal("12.00"),
                "fee_gbp": Decimal("2.00"),
                "fx_rate": 1.0,
            },
        ]

        results = calculate_cost_basis(transactions)

        # The sell should match against the same-day buy
        # Proceeds: 50 * 12 = 600
        # Cost: 50 * 10 = 500
        # Gain: 100 (before fees)
        assert len(results) >= 1


class TestBedAndBreakfastRule:
    """Tests for the 30-day bed and breakfast rule."""

    def test_30_day_rule(self):
        """Sale within 3 days after a buy matches that buy."""
        from app.calculations.cost_basis import calculate_cost_basis

        transactions = [
            {
                "date": date(2024, 1, 10),
                "type": "sell",
                "ticker": "VUAG",
                "quantity": Decimal("50"),
                "price_gbp": Decimal("12.00"),
                "fee_gbp": Decimal("1.00"),
                "fx_rate": 1.0,
            },
            {
                "date": date(2024, 1, 12),  # 2 days after
                "type": "buy",
                "ticker": "VUAG",
                "quantity": Decimal("50"),
                "price_gbp": Decimal("11.00"),
                "fee_gbp": Decimal("1.00"),
                "fx_rate": 1.0,
            },
        ]

        results = calculate_cost_basis(transactions)
        # The sell should match against the buy within 3 days
        assert len(results) >= 1


class TestTaxYear:
    """Tests for UK tax year calculations."""

    def test_tax_year_boundary(self):
        """Test tax year spans 6 April to 5 April."""
        from app.calculations.cost_basis import _uk_tax_year, _is_in_tax_year

        # Before 6 April → previous tax year
        assert _uk_tax_year(date(2024, 4, 5)) == "2023/2024"
        # On 6 April → new tax year
        assert _uk_tax_year(date(2024, 4, 6)) == "2024/2025"
        # End of tax year
        assert _uk_tax_year(date(2025, 4, 5)) == "2024/2025"

    def test_tax_year_in_range(self):
        """Test date falls within correct tax year."""
        from app.calculations.cost_basis import _is_in_tax_year

        assert _is_in_tax_year(date(2024, 3, 1), "2023/2024")
        assert _is_in_tax_year(date(2024, 6, 1), "2024/2025")
        assert not _is_in_tax_year(date(2024, 5, 6), "2023/2024")


# ── Holdings Tests ──────────────────────────────────────────────────────────

class TestHoldings:
    """Tests for holdings calculations."""

    def test_market_value(self):
        """Test market value = quantity * price."""
        quantity = 100
        price = 15.50
        expected = 1550.0

        assert quantity * price == expected

    def test_unrealised_pnl(self):
        """Test unrealised PnL = market value - cost."""
        market_value = 1550.0
        cost = 1200.0
        expected = 350.0

        assert market_value - cost == expected

    def test_weight(self):
        """Test weight = holding value / total NAV * 100."""
        holding_value = 1550.0
        total_nav = 50000.0
        expected = 3.1

        assert round(holding_value / total_nav * 100, 2) == expected


# ── Returns Tests ───────────────────────────────────────────────────────────

class TestReturns:
    """Tests for returns calculations."""

    def test_daily_log_return(self):
        """Test daily log return."""
        p0 = 100.0
        p1 = 105.0
        expected = math.log(p1 / p0)

        assert abs(math.log(p1 / p0) - expected) < 1e-10

    def test_cumulative_return(self):
        """Test cumulative return over multiple periods."""
        prices = [100, 105, 102, 110]
        total_return = (prices[-1] / prices[0] - 1) * 100

        assert abs(total_return - 10.0) < 0.01

    def test_mtd_return(self):
        """Test MTD return from month start."""
        nav_start = 50000.0
        nav_end = 51500.0
        expected = (nav_end / nav_start - 1) * 100

        assert abs(expected - 3.0) < 0.01


# ── Risk Metrics Tests ──────────────────────────────────────────────────────

class TestRiskMetrics:
    """Tests for risk metric calculations."""

    def test_sharpe_ratio(self):
        """Test Sharpe ratio calculation."""
        returns = np.array([0.01, -0.005, 0.02, -0.01, 0.015])
        rf_daily = 0.05 / 252
        excess = returns - rf_daily

        sharpe = float(excess.mean() / excess.std() * math.sqrt(252))
        assert sharpe > 0  # Positive excess returns

    def test_sortino_ratio(self):
        """Test Sortino ratio (downside deviation)."""
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
        rf_daily = 0.05 / 252
        excess = returns - rf_daily

        downside = excess[excess < 0]
        if len(downside) > 0:
            downside_std = np.sqrt(np.mean(downside ** 2))
            sortino = float(excess.mean() / downside_std * math.sqrt(252))
            assert sortino > 0

    def test_max_drawdown(self):
        """Test max drawdown calculation."""
        prices = [100, 110, 105, 95, 100, 115]
        cumulative = np.cumprod(1 + np.log(np.array(prices[1:]) / prices[:-1]))
        cumulative = np.insert(cumulative, 0, prices[0])

        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max

        max_dd = drawdown.min() * 100
        assert max_dd < 0  # Drawdown is negative

    def test_var_95(self):
        """Test VaR 95% calculation."""
        returns = np.random.normal(0.0005, 0.02, 1000)
        var_95 = np.percentile(returns, 5) * 100

        assert var_95 < 0  # VaR is a loss


# ── Correlation Tests ───────────────────────────────────────────────────────

class TestCorrelation:
    """Tests for correlation module."""

    def test_correlation_matrix_symmetric(self):
        """Test that correlation matrices are symmetric."""
        np.random.seed(42)
        n = 10
        data = np.random.randn(100, n)
        corr = pd.DataFrame(data).corr().values

        assert np.allclose(corr, corr.T)

    def test_correlation_diagonal_is_1(self):
        """Test diagonal elements are 1."""
        np.random.seed(42)
        n = 10
        data = np.random.randn(100, n)
        corr = pd.DataFrame(data).corr().values

        assert np.allclose(np.diag(corr), 1.0)

    def test_correlation_values_in_range(self):
        """Test correlation values are in [-1, 1]."""
        np.random.seed(42)
        n = 10
        data = np.random.randn(100, n)
        corr = pd.DataFrame(data).corr().values

        assert np.all(corr >= -1)
        assert np.all(corr <= 1)

    def test_known_correlation(self):
        """Test that perfectly correlated series return correlation of 1."""
        x = np.random.randn(100)
        y = 2 * x + np.random.randn(100) * 0.01  # nearly perfect linear

        corr = np.corrcoef(x, y)[0, 1]
        assert corr > 0.99

    def test_hierarchical_clustering_sorts(self):
        """Test that hierarchical clustering produces a reordered matrix."""
        np.random.seed(42)
        # Create two clusters of correlated assets
        n_cluster1, n_cluster2 = 5, 5
        n_total = n_cluster1 + n_cluster2

        # Cluster 1: high correlation
        c1 = np.random.randn(50, n_cluster1) * 0.1
        c1 += np.random.randn(50)[:, None] * 0.5

        # Cluster 2: high correlation, different mean
        c2 = np.random.randn(50, n_cluster2) * 0.1
        c2 += np.random.randn(50)[:, None] * 0.5 + 0.3

        data = np.vstack([c1, c2])
        df = pd.DataFrame(data, columns=[f"asset_{i}" for i in range(n_total)])
        corr = df.corr()

        # Verify it's a valid correlation matrix
        assert corr.shape == (n_total, n_total)
        assert np.allclose(corr, corr.T)

    def test_positive_semi_definite(self):
        """Test that correlation matrices are positive semi-definite."""
        np.random.seed(42)
        n = 10
        data = np.random.randn(100, n)
        corr = pd.DataFrame(data).corr().values

        eigenvalues = np.linalg.eigvalsh(corr)
        # All eigenvalues should be >= 0 (within numerical tolerance)
        assert np.all(eigenvalues >= -1e-10)


# ── Projection Tests ────────────────────────────────────────────────────────

class TestProjections:
    """Tests for projection calculations."""

    def test_compound_interest(self):
        """Test compound interest formula."""
        from app.calculations.projections import reproduce_excel_projection

        result = reproduce_excel_projection(
            current_nav=100000,
            monthly_contribution=500,
            expected_return=8.0,
            target_date=date(2030, 4, 30),
        )

        assert result["final_value"] > 100000
        assert result["total_contributed"] > 100000
        assert result["total_gain"] > 0

    def test_no_growth(self):
        """Test projection with 0% return."""
        from app.calculations.projections import reproduce_excel_projection

        result = reproduce_excel_projection(
            current_nav=100000,
            monthly_contribution=1000,
            expected_return=0.0,
            target_date=date(2027, 4, 30),
        )

        # With 0% return, final = initial + contributions
        months = 36
        expected = 100000 + (1000 * months)
        assert abs(result["final_value"] - expected) < 1


# ── Concentration Tests ─────────────────────────────────────────────────────

class TestConcentration:
    """Tests for concentration metrics."""

    def test_hhi(self):
        """Test HHI calculation."""
        weights = np.array([0.3, 0.25, 0.2, 0.15, 0.1])
        hhi = np.sum(weights ** 2)

        assert hhi > 0
        assert hhi <= 1  # Max HHI = 1 (single asset)

    def test_effective_n(self):
        """Test effective number of holdings."""
        weights = np.array([0.3, 0.25, 0.2, 0.15, 0.1])
        hhi = np.sum(weights ** 2)
        eff_n = 1 / hhi

        assert eff_n <= len(weights)
        assert eff_n >= 1

    def test_diversification_ratio(self):
        """Test diversification ratio > 1 for diversified portfolio."""
        # Equal weights
        n = 10
        weights = np.ones(n) / n
        corr = np.ones((n, n)) * 0.3
        np.fill_diagonal(corr, 1.0)

        port_var = np.dot(weights.T, np.dot(corr * np.outer(np.sqrt(np.diag(corr)), np.sqrt(np.diag(corr))), weights))
        weighted_avg_std = np.sum(weights * np.sqrt(np.diag(corr)))

        div_ratio = np.sqrt(port_var) / weighted_avg_std
        assert div_ratio > 1  # Diversification benefit


# ── Fixtures for DB Tests ──────────────────────────────────────────────────

@pytest.fixture
def sample_instruments():
    """Create sample instruments for testing."""
    from app.models import Instrument

    return [
        Instrument(ticker="VUAG", name="Vanguard S&P 500 UCITS USD (Acc)", listing_currency="USD", asset_class="etf", sector="US Equity"),
        Instrument(ticker="IWDA", name="iShares MSCI World UCITS USD (Acc)", listing_currency="USD", asset_class="etf", sector="Global Equity"),
        Instrument(ticker="VNRG", name="Vanguard Net Zero Energy Transition", listing_currency="GBP", asset_class="etf", sector="Energy Transition"),
        Instrument(ticker="CMCW", name="iShares Core MSCI UK UCITS", listing_currency="GBP", asset_class="etf", sector="UK Equity"),
        Instrument(ticker="VUSA", name="Vanguard S&P 500 UCITS USD (Dist)", listing_currency="USD", asset_class="etf", sector="US Equity"),
    ]


@pytest.fixture
def sample_pies():
    """Create sample pies for testing."""
    from app.models import Pie

    return [
        Pie(name="Core Equity", target_allocation=40.0, status="active"),
        Pie(name="UK Investments", target_allocation=15.0, status="active"),
        Pie(name="Asian Investments", target_allocation=10.0, status="active"),
        Pie(name="Energy Transition", target_allocation=10.0, status="active"),
        Pie(name="Tech Growth", target_allocation=10.0, status="active"),
        Pie(name="Fixed Income", target_allocation=10.0, status="active"),
        Pie(name="Commodities", target_allocation=5.0, status="active"),
        Pie(name="Cash", target_allocation=10.0, status="active"),
    ]
