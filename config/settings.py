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


class RiskConfig(BaseModel):
    """Risk Management Configuration — Institutional Credit Portfolio

    Calibrated for $250m AUM European macro credit book.
    Limits match the Brummer & Partners risk framework.
    """
    starting_capital: float = 250_000_000.0  # $250m AUM

    # Stop-loss cascade (% of NAV)
    daily_stop_loss_pct: float = 0.01       # 1.0% — flatten all, review before resuming
    weekly_stop_loss_pct: float = 0.02      # 2.0% — 50% risk reduction, regime reassessment
    monthly_drawdown_pct: float = 0.035     # 3.5% — reduce to 25% risk, CIO approval
    max_peak_to_trough_pct: float = 0.05    # 5.0% — full de-risk, strategy review

    # Concentration limits
    max_single_name_pct: float = 0.05       # 5% per name — hard limit, no exceptions
    max_sector_pct: float = 0.25            # 25% max sector concentration
    max_positions: int = 40                 # Max concurrent positions

    # Liquidity
    liquidation_days: int = 5               # 90% of portfolio liquidatable in 5 days
    min_liquidity_pct: float = 0.90         # 90% liquidity test — ongoing monitoring

    # Legacy compatibility
    max_position_pct: float = 0.05
    max_daily_loss_pct: float = 0.01


class SignalConfig(BaseModel):
    """Signal Generation Configuration"""
    min_risk_reward: float = 2.0  # Minimum 2:1 risk/reward
    min_confidence: float = 0.65  # 65% minimum confidence
    lookback_periods: int = 100


class StrategyConfig(BaseModel):
    """
    European Macro Credit Trading Strategies.

    CDS | Tranches | Bonds | Credit Options
    Focused on iTraxx Main (125 names) and Crossover (75 names).
    """

    # Credit trading strategies — each maps to the process pipeline
    proven_strategies: Dict[str, Dict] = {
        'documentation_mispricing': {
            'enabled': True,
            'instruments': ['cds', 'bonds'],
            'description': 'Covenant analysis reveals mispriced credit risk — weak RP baskets, portability, J.Crew blockers',
            'edge': 'information_gap',
        },
        'credit_catalyst': {
            'enabled': True,
            'instruments': ['cds', 'tranches', 'bonds'],
            'description': 'Filing anomalies, rating actions, earnings misses — identify catalysts before spread moves',
            'edge': 'speed_and_analysis',
        },
        'basis_trade': {
            'enabled': True,
            'instruments': ['cds', 'bonds'],
            'description': 'CDS-bond basis trades — exploit dislocations between cash and synthetic markets',
            'edge': 'relative_value',
        },
        'tranche_technical': {
            'enabled': True,
            'instruments': ['tranches'],
            'description': 'Index tranche mispricings from hedger/yield-seeker imbalances — equity/mezzanine/senior',
            'edge': 'structural_technical',
        },
        'correlation_dispersion': {
            'enabled': True,
            'instruments': ['tranches', 'cds'],
            'description': 'Single-name vs index correlation trades — tranches adjust slower than constituent changes',
            'edge': 'structural_technical',
        },
        'relative_value': {
            'enabled': True,
            'instruments': ['cds', 'bonds'],
            'description': 'Rich/cheap screening — sector z-scores, cross-currency, maturity curve',
            'edge': 'quantitative',
        },
    }

    # Disabled strategies
    disabled_strategies: List[str] = []

    # iTraxx universe — not equity symbols
    priority_symbols: Dict[str, List[str]] = {
        'main_widest': [
            'Suedzucker AG', 'Stellantis NV', 'WPP 2005 Ltd',
            'PostNL NV', 'Electrolux AB',
        ],
        'xover_distressed': [
            'INEOS Quattro Finance 2 Plc', 'Worldline SA/France',
            'INEOS Finance PLC', 'Bellis Acquisition Co PLC',
            'Sherwood Financing PLC',
        ],
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
    Capital allocation across European macro credit instruments.

    $250m book — CDS, tranches, bonds, credit options.
    """
    # Priority weights by instrument
    cds: float = 1.00           # Core — single-name and index CDS
    tranches: float = 0.95      # Index tranches (equity, mezzanine, senior)
    bonds: float = 0.85         # Cash bonds — basis trades, RV
    credit_options: float = 0.80  # CDS swaptions, credit options

    # Capital allocation
    cds_capital_pct: float = 0.40       # 40% to CDS
    tranches_capital_pct: float = 0.30  # 30% to tranches
    bonds_capital_pct: float = 0.20     # 20% to cash bonds
    options_capital_pct: float = 0.05   # 5% to credit options
    reserve_pct: float = 0.05           # 5% cash reserve

    # Scan intervals (seconds) — all credit focused
    credit_scan_interval: int = 15      # Every 15s — primary market
    filing_scan_interval: int = 60      # Every 60s — regulatory filings
    news_scan_interval: int = 30        # Every 30s — news/sentiment

    # Adaptive learning
    adaptive_enabled: bool = True
    adapt_interval_hours: int = 24
    min_trades_to_adapt: int = 10
    max_weight_shift: float = 0.15

    def get_weight(self, instrument_type: str) -> float:
        """Get weight for an instrument type"""
        weights = {
            'cds': self.cds,
            'tranches': self.tranches,
            'bonds': self.bonds,
            'credit_options': self.credit_options,
            # Legacy aliases
            'credit': self.cds,
            'options': self.credit_options,
            'equity': self.bonds,
        }
        return weights.get(instrument_type, 0.5)

    def get_capital_allocation(self, instrument_type: str, total_capital: float) -> float:
        """Get capital allocated to an instrument type"""
        allocations = {
            'cds': self.cds_capital_pct,
            'tranches': self.tranches_capital_pct,
            'bonds': self.bonds_capital_pct,
            'credit_options': self.options_capital_pct,
            # Legacy aliases
            'credit': self.cds_capital_pct,
            'options': self.options_capital_pct,
        }
        pct = allocations.get(instrument_type, 0.0)
        return total_capital * pct

    def get_scan_interval(self, scan_type: str) -> int:
        """Get scan interval for a scan type"""
        intervals = {
            'credit': self.credit_scan_interval,
            'filing': self.filing_scan_interval,
            'news': self.news_scan_interval,
        }
        return intervals.get(scan_type, 60)


class EdgeLearningConfig(BaseModel):
    """
    Edge Component Learning Configuration.
    Controls how the system learns optimal edge score component weights
    from trade outcomes.
    """
    enabled: bool = True
    min_trades_to_adapt: int = 20       # Need 20 trades before adapting
    adapt_interval_hours: int = 24      # Re-evaluate weights daily
    max_weight_shift: float = 0.15      # Max 15% shift per adaptation cycle
    min_component_weight: float = 0.05  # Never disable a component (5% floor)
    max_component_weight: float = 0.40  # No single component dominates (40% cap)
    lookback_days: int = 90             # Lookback window for performance calc


class ScannerConfig(BaseModel):
    """Market Scanner Configuration"""
    scan_interval_seconds: int = 60
    credit_enabled: bool = True    # Core — iTraxx Main/Xover
    equities_enabled: bool = True
    options_enabled: bool = True


class TradingConfig(BaseModel):
    """Main Trading Configuration"""
    ib: IBConfig = IBConfig()
    risk: RiskConfig = RiskConfig()
    signals: SignalConfig = SignalConfig()
    scanner: ScannerConfig = ScannerConfig()
    market_weights: MarketWeights = MarketWeights()
    strategies: StrategyConfig = StrategyConfig()
    edge_learning: EdgeLearningConfig = EdgeLearningConfig()

    # Environment
    live_trading: bool = True
    log_level: str = "INFO"


# Global config instance
config = TradingConfig()
