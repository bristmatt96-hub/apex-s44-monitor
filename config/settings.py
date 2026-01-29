"""
Trading System Configuration
"""
from pydantic import BaseModel
from typing import Optional, Dict, List
import os
from dotenv import load_dotenv

load_dotenv()


class IBConfig(BaseModel):
    """Interactive Brokers Configuration"""
    host: str = "127.0.0.1"
    port: int = 4002  # 4002 for Gateway paper, 4001 for Gateway live, 7497/7496 for TWS
    client_id: int = 1
    account: Optional[str] = None


class CryptoConfig(BaseModel):
    """Crypto Exchange Configuration"""
    exchange: str = "kraken"  # UK-friendly exchange
    api_key: str = os.getenv("KRAKEN_API_KEY", "")
    api_secret: str = os.getenv("KRAKEN_API_SECRET", "")
    testnet: bool = False


class RiskConfig(BaseModel):
    """Risk Management Configuration"""
    max_position_pct: float = 0.05  # 5% max per position
    max_daily_loss_pct: float = 0.10  # 10% max daily loss
    max_positions: int = 10
    starting_capital: float = 3000.0


class SignalConfig(BaseModel):
    """Signal Generation Configuration"""
    min_risk_reward: float = 2.0  # Minimum 2:1 risk/reward
    min_confidence: float = 0.65  # 65% minimum confidence
    lookback_periods: int = 100


class StrategyConfig(BaseModel):
    """
    Strategy configuration based on backtest results.

    Only strategies with proven statistical edge are enabled.
    Backtest criteria: Profit Factor > 1.2 AND Win Rate > 40%
    """

    # Proven strategies and their backtest performance
    proven_strategies: Dict[str, Dict] = {
        'mean_reversion': {
            'enabled': True,
            'markets': ['crypto', 'equity', 'options', 'etf'],
            'best_market': 'etf',
            'avg_profit_factor': 2.66,
            'avg_win_rate': 0.599,
            'score_bonus': 1.15,  # 15% score boost
            'description': 'Buy RSI oversold panic dips, exit on bounce'
        },
        'volume_spike': {
            'enabled': True,
            'markets': ['crypto', 'equity', 'options'],
            'best_market': 'crypto',
            'avg_profit_factor': 5.30,
            'avg_win_rate': 0.673,
            'score_bonus': 1.20,  # 20% boost (highest edge)
            'description': 'Buy when retail panic-sells on huge red volume'
        },
        'momentum_breakout': {
            'enabled': True,
            'markets': ['crypto', 'equity', 'options', 'etf'],
            'best_market': 'crypto',
            'avg_profit_factor': 1.93,
            'avg_win_rate': 0.557,
            'score_bonus': 1.10,  # 10% boost
            'description': 'Breakout above 20-day high with volume confirmation'
        },
        'bollinger_squeeze': {
            'enabled': True,
            'markets': ['crypto', 'equity', 'options', 'etf'],
            'best_market': 'equity',
            'avg_profit_factor': 1.50,  # Estimated pending full backtest
            'avg_win_rate': 0.50,
            'score_bonus': 1.05,  # Small boost until validated
            'description': 'Low volatility squeeze breakout'
        },
        'insider_buying': {
            'enabled': True,
            'markets': ['equity'],
            'best_market': 'equity',
            'avg_profit_factor': 2.50,  # Academic studies show ~2-3x edge
            'avg_win_rate': 0.60,
            'score_bonus': 1.25,  # 25% boost - strongest fundamental signal
            'description': 'SEC Form 4 insider purchases (CEO/CFO/Directors)'
        },
        'unusual_options_flow': {
            'enabled': True,
            'markets': ['equity', 'options'],
            'best_market': 'options',
            'avg_profit_factor': 2.00,  # Based on academic flow studies
            'avg_win_rate': 0.55,
            'score_bonus': 1.18,  # 18% boost - strong informed money signal
            'description': 'Unusual options V/OI ratio, sweeps, and premium concentration'
        },
    }

    # Disabled strategies (no proven edge)
    disabled_strategies: List[str] = ['rsi_divergence', 'gap_fade']

    # Priority symbol lists per market (backtest-proven performers)
    priority_symbols: Dict[str, List[str]] = {
        'crypto': [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'DOGE-USD',
            'ADA-USD', 'XRP-USD', 'AVAX-USD'
        ],
        'options_stocks': [
            'SPY', 'QQQ', 'TSLA', 'AAPL', 'NVDA', 'AMD',
            'META', 'AMZN', 'MSFT', 'GOOGL', 'NFLX', 'COIN'
        ],
        'meme_stocks': [
            'GME', 'AMC', 'PLTR', 'SOFI', 'BB',
            'HOOD', 'RIVN', 'LCID', 'MARA', 'RIOT'
        ],
        'etfs': [
            'SPY', 'QQQ', 'IWM', 'ARKK', 'TQQQ',
            'GLD', 'SLV', 'XLE', 'XLF', 'TLT'
        ],
        'small_cap': [
            'SOFI', 'PLTR', 'MARA', 'RIOT', 'JOBY',
            'IONQ', 'RKLB', 'DNA', 'OPEN'
        ]
    }

    def is_strategy_enabled(self, strategy_name: str) -> bool:
        """Check if a strategy is enabled"""
        if strategy_name in self.disabled_strategies:
            return False
        strat = self.proven_strategies.get(strategy_name)
        return strat is not None and strat.get('enabled', False)

    def get_strategy_bonus(self, strategy_name: str) -> float:
        """Get score multiplier for a proven strategy"""
        strat = self.proven_strategies.get(strategy_name)
        if strat and strat.get('enabled'):
            return strat.get('score_bonus', 1.0)
        return 0.85  # 15% penalty for unproven strategies

    def get_best_strategies_for_market(self, market_type: str) -> List[str]:
        """Get ranked strategies for a market type"""
        results = []
        for name, data in self.proven_strategies.items():
            if data.get('enabled') and market_type in data.get('markets', []):
                results.append((name, data.get('avg_profit_factor', 0)))
        results.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in results]


class MarketWeights(BaseModel):
    """
    Market priority weights and capital allocation.
    UPDATED based on backtest results (Jan 2026).

    Weights determine:
    - Scanner priority (higher = scanned more frequently)
    - Ranker bonus (higher weight = boosted score)
    - Capital allocation (% of total capital for that market)

    These are INITIAL weights. The adaptive system will
    adjust them based on actual trading performance.
    """
    # Priority weights - updated from backtest results
    # Crypto had highest avg PF (6.18 across winning strategies)
    # Options stocks second (2.44 avg PF)
    # ETFs strong on mean reversion (PF 5.29)
    crypto: float = 0.95        # Highest - PF 14.42 volume spike, no PDT, 24/7
    options: float = 0.90       # High - 4 strategies with edge, best R:R for $3k
    equities: float = 0.70      # Medium-high - mean reversion + volume spike proven
    forex: float = 0.45         # Lower - no backtest data yet
    spacs: float = 0.0          # Disabled

    # Capital allocation - increased crypto based on results
    crypto_capital_pct: float = 0.30    # $900 (highest edge)
    options_capital_pct: float = 0.35   # $1,050 (best R:R structure)
    equities_capital_pct: float = 0.20  # $600 (mean reversion + volume spike)
    forex_capital_pct: float = 0.10     # $300 (untested, keep small)
    spacs_capital_pct: float = 0.0      # $0
    reserve_pct: float = 0.05           # $150 cash reserve

    # Scan intervals (seconds) - lower = more frequent
    options_scan_interval: int = 30     # Every 30s
    crypto_scan_interval: int = 30      # Every 30s
    equities_scan_interval: int = 60    # Every 60s
    forex_scan_interval: int = 60       # Every 60s

    # Adaptive learning
    adaptive_enabled: bool = True
    adapt_interval_hours: int = 24      # Re-evaluate weights daily
    min_trades_to_adapt: int = 10       # Need 10 trades before adapting
    max_weight_shift: float = 0.15      # Max 15% shift per adaptation

    def get_weight(self, market_type: str) -> float:
        """Get weight for a market type"""
        weights = {
            'options': self.options,
            'crypto': self.crypto,
            'equity': self.equities,
            'forex': self.forex,
            'spac': self.spacs
        }
        return weights.get(market_type, 0.5)

    def get_capital_allocation(self, market_type: str, total_capital: float) -> float:
        """Get capital allocated to a market"""
        allocations = {
            'options': self.options_capital_pct,
            'crypto': self.crypto_capital_pct,
            'equity': self.equities_capital_pct,
            'forex': self.forex_capital_pct,
            'spac': self.spacs_capital_pct
        }
        pct = allocations.get(market_type, 0.0)
        return total_capital * pct

    def get_scan_interval(self, market_type: str) -> int:
        """Get scan interval for a market"""
        intervals = {
            'options': self.options_scan_interval,
            'crypto': self.crypto_scan_interval,
            'equity': self.equities_scan_interval,
            'forex': self.forex_scan_interval
        }
        return intervals.get(market_type, 60)


class ScannerConfig(BaseModel):
    """Market Scanner Configuration"""
    scan_interval_seconds: int = 60
    equities_enabled: bool = True
    crypto_enabled: bool = True
    forex_enabled: bool = True
    options_enabled: bool = True
    spacs_enabled: bool = False  # Disabled by default


class TradingConfig(BaseModel):
    """Main Trading Configuration"""
    ib: IBConfig = IBConfig()
    crypto: CryptoConfig = CryptoConfig()
    risk: RiskConfig = RiskConfig()
    signals: SignalConfig = SignalConfig()
    scanner: ScannerConfig = ScannerConfig()
    market_weights: MarketWeights = MarketWeights()
    strategies: StrategyConfig = StrategyConfig()

    # PDT Rule - limited day trades for accounts under $25k
    pdt_restricted: bool = True
    day_trades_remaining: int = 3

    # Environment
    live_trading: bool = True
    log_level: str = "INFO"


# Global config instance
config = TradingConfig()
