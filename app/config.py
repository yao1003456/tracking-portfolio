"""Application configuration. All secrets from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./great_dyne_meridian.db"

    # Security
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours

    # Price data
    price_cache_dir: str = "./cache/prices"
    fx_cache_dir: str = "./cache/fx"

    # Correlation thresholds (configurable in UI later)
    correlation_alert_threshold: float = 0.85
    avg_pairwise_corr_threshold: float = 0.7
    effective_bets_min: int = 5
    pie_to_vuag_corr_threshold: float = 0.8

    # Risk-free rate source: UK Bank Rate (fetched from BoE)
    risk_free_rate_source: str = "bank_of_england"

    # Benchmarks
    benchmark_sp500_ticker: str = "VUAG.L"
    benchmark_msci_world_ticker: str = "IWDA.L"

    # Tax settings (UK)
    annual_exempt_amount: float = 3000.0  # 2024/25 allowance
    dividend_allowance: float = 500.0

    # Settings
    base_currency: str = "GBP"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
