"""
Credit Catalyst Configuration Settings

Environment-based configuration for the credit catalyst trading system.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class TelegramConfig:
    """Telegram bot configuration."""
    bot_token: str
    chat_id: str
    enabled: bool = True


@dataclass
class AnthropicConfig:
    """Anthropic API configuration."""
    api_key: str
    model: str = "claude-3-sonnet-20240229"
    max_tokens: int = 4096


@dataclass
class SECConfig:
    """SEC EDGAR configuration."""
    user_agent: str = "CreditCatalyst/0.1 (contact@example.com)"
    rate_limit_seconds: float = 0.1  # SEC requires 10 requests/second max
    check_interval_minutes: int = 15


@dataclass
class AlertConfig:
    """Alert configuration."""
    # Spread thresholds (basis points)
    spread_minor_bps: int = 25
    spread_moderate_bps: int = 50
    spread_severe_bps: int = 100
    spread_crisis_bps: int = 200

    # Alert cooldown (minutes)
    cooldown_minutes: int = 60


@dataclass
class DatabaseConfig:
    """Database configuration."""
    path: str = "credit_catalyst.db"


@dataclass
class Settings:
    """Main settings container."""
    telegram: Optional[TelegramConfig]
    anthropic: Optional[AnthropicConfig]
    sec: SECConfig
    alerts: AlertConfig
    database: DatabaseConfig

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""

        # Telegram config
        telegram = None
        tg_token = os.getenv("CREDIT_TELEGRAM_BOT_TOKEN")
        tg_chat = os.getenv("CREDIT_TELEGRAM_CHAT_ID")
        if tg_token and tg_chat:
            telegram = TelegramConfig(
                bot_token=tg_token,
                chat_id=tg_chat,
                enabled=os.getenv("CREDIT_TELEGRAM_ENABLED", "true").lower() == "true"
            )

        # Anthropic config
        anthropic = None
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            anthropic = AnthropicConfig(
                api_key=anthropic_key,
                model=os.getenv("CREDIT_ANTHROPIC_MODEL", "claude-3-sonnet-20240229"),
                max_tokens=int(os.getenv("CREDIT_ANTHROPIC_MAX_TOKENS", "4096"))
            )

        # SEC config
        sec = SECConfig(
            user_agent=os.getenv(
                "CREDIT_SEC_USER_AGENT",
                "CreditCatalyst/0.1 (contact@example.com)"
            ),
            rate_limit_seconds=float(os.getenv("CREDIT_SEC_RATE_LIMIT", "0.1")),
            check_interval_minutes=int(os.getenv("CREDIT_SEC_CHECK_INTERVAL", "15"))
        )

        # Alert config
        alerts = AlertConfig(
            spread_minor_bps=int(os.getenv("CREDIT_SPREAD_MINOR_BPS", "25")),
            spread_moderate_bps=int(os.getenv("CREDIT_SPREAD_MODERATE_BPS", "50")),
            spread_severe_bps=int(os.getenv("CREDIT_SPREAD_SEVERE_BPS", "100")),
            spread_crisis_bps=int(os.getenv("CREDIT_SPREAD_CRISIS_BPS", "200")),
            cooldown_minutes=int(os.getenv("CREDIT_ALERT_COOLDOWN", "60"))
        )

        # Database config
        database = DatabaseConfig(
            path=os.getenv("CREDIT_DATABASE_PATH", "credit_catalyst.db")
        )

        return cls(
            telegram=telegram,
            anthropic=anthropic,
            sec=sec,
            alerts=alerts,
            database=database
        )


# Global settings instance
settings = Settings.from_env()
