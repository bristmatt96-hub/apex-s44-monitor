"""
Credit Catalyst Configuration

Pydantic settings for the credit analysis system.
Replaces the old trading-focused config/settings.py.
"""

from pydantic import BaseModel
from typing import Optional, Dict, List
import os
from dotenv import load_dotenv

load_dotenv()


class LLMConfig(BaseModel):
    """Claude API Configuration."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")


class DatabaseConfig(BaseModel):
    """Database Configuration."""
    url: str = os.getenv("DATABASE_URL", "sqlite:///data/credit_catalyst.db")
    echo: bool = False


class TelegramConfig(BaseModel):
    """Telegram Alert Configuration."""
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    enabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)


class MonitorConfig(BaseModel):
    """Monitor Layer Configuration."""
    # Scan intervals (seconds)
    regulatory_filing_interval: int = 60
    rating_action_interval: int = 300
    news_sentiment_interval: int = 120
    social_sentiment_interval: int = 180
    earnings_interval: int = 300
    market_data_interval: int = 30

    # API keys for data sources
    companies_house_api_key: str = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    twitter_bearer_token: str = os.getenv("TWITTER_BEARER_TOKEN", "")
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")


class AnalyticsConfig(BaseModel):
    """Analytics Engine Configuration."""
    default_recovery_rate: float = 0.40
    default_discount_rate: float = 0.03
    default_maturity_years: float = 5.0
    scenario_count: int = 9
    backtest_lookback_years: int = 5


class IndexConfig(BaseModel):
    """Index Configuration."""
    itraxx_main_series: int = 44
    itraxx_main_names: int = 125
    itraxx_xover_series: int = 44
    itraxx_xover_names: int = 75


class CreditCatalystConfig(BaseModel):
    """Main Credit Catalyst Configuration."""
    llm: LLMConfig = LLMConfig()
    database: DatabaseConfig = DatabaseConfig()
    telegram: TelegramConfig = TelegramConfig()
    monitors: MonitorConfig = MonitorConfig()
    analytics: AnalyticsConfig = AnalyticsConfig()
    indices: IndexConfig = IndexConfig()

    # Environment
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


# Global config instance
settings = CreditCatalystConfig()
