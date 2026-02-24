#!/usr/bin/env python3
"""
Credit Backtest Engine
=======================
Test conditional macro-credit trading strategies against historical data.

Example queries this engine answers:
  - "How did long HY / short IG perform when ISM was falling but above 50?"
  - "What happens to CCC vs BB when VIX crosses above 25?"
  - "Does buying Xover protection when the curve inverts pay off?"
  - "What's the hit rate of going long EUR HY when it's >1 Z-score wide?"

Architecture:
  1. CONDITIONS  - Flexible signal conditions on any macro/market series
  2. STRATEGIES  - Pre-built and custom credit relative value strategies
  3. ENGINE      - Runs the backtest: when conditions are met, enter strategy
  4. ANALYTICS   - Hit rate, avg return, Sharpe, drawdown, conditional distributions
  5. LIBRARY     - Pre-built backtests for common macro-credit questions

Usage:
  pip install fredapi pandas matplotlib numpy scipy
  set FRED_API_KEY=your_key_here
  python -m analytics.credit_backtest_engine
  python -m analytics.credit_backtest_engine --json
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Callable
from enum import Enum

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_YEARS = 15
START_DATE = datetime.now() - timedelta(days=365 * HISTORY_YEARS)


# =============================================================================
# FRED SERIES REGISTRY
# =============================================================================

FRED_REGISTRY = {
    # Credit Spreads
    "US_HY":       "BAMLH0A0HYM2",
    "US_BB":       "BAMLH0A1HYBB",
    "US_B":        "BAMLH0A2HYB",
    "US_CCC":      "BAMLH0A3HYC",
    "US_IG":       "BAMLC0A0CM",
    "US_BBB":      "BAMLC0A4CBBB",
    "EUR_HY":      "BAMLHE00EHYIOAS",

    # Yields
    "US_HY_YLD":   "BAMLH0A0HYM2EY",
    "US_BB_YLD":   "BAMLH0A1HYBBEY",

    # Rates
    "UST_2Y":      "DGS2",
    "UST_5Y":      "DGS5",
    "UST_10Y":     "DGS10",
    "UST_30Y":     "DGS30",
    "TIPS_5Y":     "DFII5",
    "TIPS_10Y":    "DFII10",

    # Macro
    "ISM":         "MANEMP",
    "CLAIMS":      "ICSA",
    "FED_FUNDS":   "FEDFUNDS",
    "SLOOS":       "DRTSCILM",

    # Equity & Vol
    "SPX":         "SP500",
    "VIX":         "VIXCLS",
    "VIX3M":       "VXVCLS",

    # FX
    "EURUSD":      "DEXUSEU",
    "DXY":         "DTWEXBGS",

    # Commodities
    "WTI":         "DCOILWTICO",
    "GOLD":        "NASDAQQGLDI",
    "COPPER":      "PCOPPUSDM",

    # Corporate
    "MOODY_BAA":   "BAA",
    "MOODY_AAA":   "AAA",
    "BAA_10Y":     "BAA10Y",

    # European
    "ECB_RATE":    "ECBMRRFR",
    "BUND_10Y":    "IRLTLT01DEM156N",
    "BTP_10Y":     "IRLTLT01ITM156N",
}


# =============================================================================
# DATA LAYER
# =============================================================================


class DataManager:
    """Fetches, caches, and serves all data needed for backtests."""

    def __init__(self):
        self.raw: pd.DataFrame = pd.DataFrame()
        self.derived: pd.DataFrame = pd.DataFrame()
        self._loaded = False

    def load(self):
        """Fetch all data from FRED."""
        from fredapi import Fred

        api_key = os.environ.get("FRED_API_KEY", "")
        if not api_key:
            print("ERROR: Set FRED_API_KEY environment variable.")
            print("  Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")
            sys.exit(1)

        fred = Fred(api_key=api_key)
        frames = {}

        print("=" * 70)
        print("  LOADING DATA FROM FRED")
        print("=" * 70)

        for key, sid in FRED_REGISTRY.items():
            try:
                s = fred.get_series(sid, observation_start=START_DATE)
                frames[key] = s
                n = len(s.dropna())
                latest = s.dropna().iloc[-1] if n > 0 else "N/A"
                dt = s.dropna().index[-1].strftime("%Y-%m-%d") if n > 0 else "N/A"
                print(f"  [OK]   {key:15s} ({sid:20s}) | {dt} = {latest}")
            except Exception as e:
                print(f"  [FAIL] {key:15s} ({sid:20s}) | {e}")

        raw = pd.DataFrame(frames)
        raw.index = pd.to_datetime(raw.index)
        self.raw = raw.resample("B").last().ffill(limit=10)
        self._compute_derived()
        self._loaded = True
        print(f"\n  Loaded {len(self.raw.columns)} series, {len(self.raw)} business days")

    def _compute_derived(self):
        """Compute commonly needed derived series."""
        df = self.raw.copy()

        # Curve
        if "UST_10Y" in df and "UST_2Y" in df:
            df["CURVE_2S10S"] = df["UST_10Y"] - df["UST_2Y"]
        if "UST_30Y" in df and "UST_10Y" in df:
            df["CURVE_10S30S"] = df["UST_30Y"] - df["UST_10Y"]
        if "TIPS_5Y" in df and "UST_5Y" in df:
            df["BREAKEVEN_5Y"] = df["UST_5Y"] - df["TIPS_5Y"]

        # Spread ratios
        if "US_HY" in df and "US_IG" in df:
            df["HY_IG_RATIO"] = df["US_HY"] / df["US_IG"]
        if "US_CCC" in df and "US_BB" in df:
            df["CCC_BB_RATIO"] = df["US_CCC"] / df["US_BB"]
        if "US_B" in df and "US_BB" in df:
            df["B_BB_SPREAD"] = df["US_B"] - df["US_BB"]
        if "EUR_HY" in df and "US_HY" in df:
            df["EUR_US_HY_RATIO"] = df["EUR_HY"] / df["US_HY"]

        # BTP-Bund
        if "BTP_10Y" in df and "BUND_10Y" in df:
            df["BTP_BUND"] = (df["BTP_10Y"] - df["BUND_10Y"]) * 100  # in bps

        # VIX term structure
        if "VIX" in df and "VIX3M" in df:
            df["VIX_TERM"] = df["VIX"] / df["VIX3M"]

        # Equity
        if "SPX" in df:
            df["SPX_RET_21D"] = df["SPX"].pct_change(21) * 100
            df["SPX_RET_63D"] = df["SPX"].pct_change(63) * 100
            df["SPX_RVOL_21D"] = df["SPX"].pct_change().rolling(21).std() * np.sqrt(252) * 100
            df["SPX_52W_HIGH"] = df["SPX"].rolling(252).max()
            df["SPX_DRAWDOWN"] = (df["SPX"] / df["SPX_52W_HIGH"] - 1) * 100

        # Copper/Gold
        if "COPPER" in df and "GOLD" in df:
            df["CU_AU_RATIO"] = df["COPPER"] / df["GOLD"]

        # Spread changes (forward-looking for backtest targets)
        for key in ["US_HY", "US_BB", "US_B", "US_CCC", "US_IG", "EUR_HY", "US_BBB"]:
            if key in df:
                df[f"{key}_CHG_21D"] = df[key].shift(-21) - df[key]    # 1 month forward
                df[f"{key}_CHG_63D"] = df[key].shift(-63) - df[key]    # 3 month forward
                df[f"{key}_CHG_126D"] = df[key].shift(-126) - df[key]  # 6 month forward

        # Z-scores (3-year rolling)
        for key in ["US_HY", "US_BB", "US_B", "US_CCC", "US_IG", "EUR_HY", "VIX"]:
            if key in df:
                m = df[key].rolling(756, min_periods=252).mean()
                s = df[key].rolling(756, min_periods=252).std().replace(0, np.nan)
                df[f"{key}_ZSCORE"] = (df[key] - m) / s

        # ISM momentum
        if "ISM" in df:
            df["ISM_MOM_3M"] = df["ISM"].diff(3)   # 3-month change
            df["ISM_MOM_6M"] = df["ISM"].diff(6)
            df["ISM_ABOVE_50"] = (df["ISM"] > 50).astype(int)
            df["ISM_FALLING"] = (df["ISM_MOM_3M"] < 0).astype(int)

        self.derived = df

    def get(self, column: str) -> pd.Series:
        """Get a series by name from derived DataFrame."""
        if column in self.derived.columns:
            return self.derived[column]
        raise KeyError(f"Series '{column}' not found. Available: {sorted(self.derived.columns)}")

    def available(self) -> List[str]:
        """List all available series."""
        return sorted(self.derived.columns.tolist())


# =============================================================================
# CONDITIONS
# =============================================================================


class Operator(Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    BETWEEN = "between"
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"


@dataclass
class Condition:
    """A single condition on a data series."""
    series: str           # column name in DataManager
    operator: Operator
    value: float          # threshold value (or lower bound for BETWEEN)
    value2: float = 0     # upper bound for BETWEEN

    def evaluate(self, data: pd.DataFrame) -> pd.Series:
        """Return boolean Series where condition is True."""
        s = data[self.series]

        if self.operator == Operator.GT:
            return s > self.value
        elif self.operator == Operator.GTE:
            return s >= self.value
        elif self.operator == Operator.LT:
            return s < self.value
        elif self.operator == Operator.LTE:
            return s <= self.value
        elif self.operator == Operator.EQ:
            return s == self.value
        elif self.operator == Operator.BETWEEN:
            return (s >= self.value) & (s <= self.value2)
        elif self.operator == Operator.CROSS_ABOVE:
            return (s > self.value) & (s.shift(1) <= self.value)
        elif self.operator == Operator.CROSS_BELOW:
            return (s < self.value) & (s.shift(1) >= self.value)
        else:
            return pd.Series(False, index=data.index)

    def __str__(self):
        if self.operator == Operator.BETWEEN:
            return f"{self.series} between {self.value} and {self.value2}"
        elif self.operator in (Operator.CROSS_ABOVE, Operator.CROSS_BELOW):
            return f"{self.series} {self.operator.value} {self.value}"
        return f"{self.series} {self.operator.value} {self.value}"


@dataclass
class ConditionSet:
    """Multiple conditions combined with AND logic."""
    conditions: List[Condition]
    name: str = ""

    def evaluate(self, data: pd.DataFrame) -> pd.Series:
        """Return boolean Series where ALL conditions are True."""
        mask = pd.Series(True, index=data.index)
        for c in self.conditions:
            if c.series in data.columns:
                mask = mask & c.evaluate(data)
            else:
                print(f"  WARNING: Series '{c.series}' not found, skipping condition")
        return mask

    def __str__(self):
        return " AND ".join(str(c) for c in self.conditions)


# =============================================================================
# STRATEGIES
# =============================================================================


@dataclass
class Strategy:
    """A credit trading strategy with long and short legs."""
    name: str
    description: str
    long_leg: str       # series name for long position (spread tightening = profit)
    short_leg: str      # series name for short position (spread widening = profit), or "" for outright
    holding_period: int  # days
    long_weight: float = 1.0
    short_weight: float = 1.0
    carry_bps: float = 0  # estimated annual carry in bps (positive = earning)


# Pre-built strategies
STRATEGY_LIBRARY = {
    "long_HY_short_IG": Strategy(
        name="Long HY / Short IG",
        description="Sell HY protection, buy IG protection. Profits from HY outperformance.",
        long_leg="US_HY", short_leg="US_IG",
        holding_period=63,
        carry_bps=250,
    ),
    "long_EUR_HY": Strategy(
        name="Long EUR HY (outright)",
        description="Sell EUR HY protection outright. Pure spread tightening + carry bet.",
        long_leg="EUR_HY", short_leg="",
        holding_period=63,
        carry_bps=300,
    ),
    "long_BB_short_CCC": Strategy(
        name="Long BB / Short CCC (up in quality)",
        description="Up-in-quality trade. Sell BB protection, buy CCC protection.",
        long_leg="US_CCC", short_leg="US_BB",
        holding_period=63,
        carry_bps=-150,  # negative carry: CCC earns more than BB
    ),
    "long_CCC_short_BB": Strategy(
        name="Long CCC / Short BB (down in quality)",
        description="Down-in-quality. Sell CCC protection, buy BB protection.",
        long_leg="US_BB", short_leg="US_CCC",
        holding_period=63,
        carry_bps=150,
    ),
    "long_EUR_short_US_HY": Strategy(
        name="Long EUR HY / Short US HY",
        description="Relative value: EUR HY tightens vs US HY.",
        long_leg="EUR_HY", short_leg="US_HY",
        holding_period=63,
        carry_bps=0,
    ),
    "long_BBB_short_BB": Strategy(
        name="Long BBB / Short BB (crossover trade)",
        description="Fallen angel boundary. Long IG BBB, short HY BB.",
        long_leg="US_BB", short_leg="US_BBB",
        holding_period=63,
        carry_bps=80,
    ),
    "short_HY": Strategy(
        name="Short HY (buy protection)",
        description="Buy HY protection outright. Pure spread widening bet.",
        long_leg="", short_leg="US_HY",
        holding_period=63,
        carry_bps=-350,  # paying spread
    ),
    "long_HY": Strategy(
        name="Long US HY (outright)",
        description="Sell US HY protection outright.",
        long_leg="US_HY", short_leg="",
        holding_period=63,
        carry_bps=350,
    ),
}


# =============================================================================
# BACKTEST ENGINE
# =============================================================================


@dataclass
class BacktestResult:
    """Results from a single backtest run."""
    name: str
    strategy: Strategy
    conditions: ConditionSet
    # Per-trade data
    trades: pd.DataFrame
    # Summary stats
    n_signals: int
    n_trades: int
    hit_rate: float
    avg_return_bps: float
    median_return_bps: float
    total_return_bps: float
    sharpe: float
    max_drawdown_bps: float
    win_avg_bps: float
    loss_avg_bps: float
    profit_factor: float
    avg_days_held: float
    # Conditional stats
    pct_time_in_signal: float


def run_backtest(
    data: pd.DataFrame,
    conditions: ConditionSet,
    strategy: Strategy,
    min_gap_days: int = 21,  # minimum days between new trades (avoid overlap)
) -> BacktestResult:
    """
    Run a backtest:
    1. Identify dates where all conditions are True
    2. At each signal date, calculate forward P&L from strategy
    3. Aggregate statistics

    P&L calculation (in bps):
    - For long leg: P&L = -(spread_change) * long_weight
      (spread tightening = positive for long credit)
    - For short leg: P&L = +(spread_change) * short_weight
      (spread widening = positive for short credit / long protection)
    - Carry: (carry_bps / 252) * holding_period
    """
    # Evaluate conditions
    signal = conditions.evaluate(data)
    signal_dates = data.index[signal]

    # Filter for minimum gap
    filtered_dates = []
    last_date = None
    for d in signal_dates:
        if last_date is None or (d - last_date).days >= min_gap_days:
            filtered_dates.append(d)
            last_date = d

    # Calculate forward returns for each trade
    trades = []
    hp = strategy.holding_period

    for entry_date in filtered_dates:
        entry_idx = data.index.get_loc(entry_date)
        exit_idx = entry_idx + hp

        if exit_idx >= len(data):
            continue  # not enough forward data

        exit_date = data.index[exit_idx]

        # Long leg P&L (spread tightening = profit)
        long_pnl = 0
        if strategy.long_leg and strategy.long_leg in data.columns:
            entry_spread = data[strategy.long_leg].iloc[entry_idx]
            exit_spread = data[strategy.long_leg].iloc[exit_idx]
            if not pd.isna(entry_spread) and not pd.isna(exit_spread):
                long_pnl = -(exit_spread - entry_spread) * strategy.long_weight

        # Short leg P&L (spread widening = profit for protection buyer)
        short_pnl = 0
        if strategy.short_leg and strategy.short_leg in data.columns:
            entry_spread = data[strategy.short_leg].iloc[entry_idx]
            exit_spread = data[strategy.short_leg].iloc[exit_idx]
            if not pd.isna(entry_spread) and not pd.isna(exit_spread):
                short_pnl = +(exit_spread - entry_spread) * strategy.short_weight

        # Carry
        carry = strategy.carry_bps * hp / 252.0

        total_pnl = long_pnl + short_pnl + carry
        spread_pnl = long_pnl + short_pnl

        trades.append({
            "entry_date": entry_date,
            "exit_date": exit_date,
            "days_held": hp,
            "long_pnl_bps": round(long_pnl, 1),
            "short_pnl_bps": round(short_pnl, 1),
            "spread_pnl_bps": round(spread_pnl, 1),
            "carry_bps": round(carry, 1),
            "total_pnl_bps": round(total_pnl, 1),
            "win": total_pnl > 0,
        })

    trades_df = pd.DataFrame(trades)

    if len(trades_df) == 0:
        return BacktestResult(
            name=f"{conditions.name} -> {strategy.name}",
            strategy=strategy, conditions=conditions,
            trades=trades_df,
            n_signals=len(signal_dates), n_trades=0,
            hit_rate=0, avg_return_bps=0, median_return_bps=0,
            total_return_bps=0, sharpe=0, max_drawdown_bps=0,
            win_avg_bps=0, loss_avg_bps=0, profit_factor=0,
            avg_days_held=0, pct_time_in_signal=0,
        )

    # Statistics
    returns = trades_df["total_pnl_bps"]
    wins = trades_df[trades_df["win"]]
    losses = trades_df[~trades_df["win"]]

    cumulative = returns.cumsum()
    running_max = cumulative.cummax()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()

    gross_wins = wins["total_pnl_bps"].sum() if len(wins) > 0 else 0
    gross_losses = abs(losses["total_pnl_bps"].sum()) if len(losses) > 0 else 0.001

    pct_in_signal = signal.sum() / len(signal) * 100

    return BacktestResult(
        name=f"{conditions.name} -> {strategy.name}",
        strategy=strategy,
        conditions=conditions,
        trades=trades_df,
        n_signals=len(signal_dates),
        n_trades=len(trades_df),
        hit_rate=len(wins) / len(trades_df) * 100,
        avg_return_bps=round(returns.mean(), 1),
        median_return_bps=round(returns.median(), 1),
        total_return_bps=round(returns.sum(), 1),
        sharpe=round(returns.mean() / returns.std(), 2) if returns.std() > 0 else 0,
        max_drawdown_bps=round(max_dd, 1),
        win_avg_bps=round(wins["total_pnl_bps"].mean(), 1) if len(wins) > 0 else 0,
        loss_avg_bps=round(losses["total_pnl_bps"].mean(), 1) if len(losses) > 0 else 0,
        profit_factor=round(gross_wins / gross_losses, 2),
        avg_days_held=round(trades_df["days_held"].mean(), 0),
        pct_time_in_signal=round(pct_in_signal, 1),
    )


# =============================================================================
# PRE-BUILT BACKTESTS (the fun part)
# =============================================================================


def build_backtest_library() -> List[Tuple[str, ConditionSet, Strategy]]:
    """
    Pre-built backtests answering common macro-credit questions.
    Each returns (name, conditions, strategy).
    """
    library = []

    # 1. ISM falling but above 50 -> Long HY / Short IG
    library.append((
        "ISM falling but >50: Long HY/Short IG",
        ConditionSet([
            Condition("ISM", Operator.GT, 50),
            Condition("ISM_MOM_3M", Operator.LT, 0),
        ], name="ISM falling >50"),
        STRATEGY_LIBRARY["long_HY_short_IG"],
    ))

    # 2. ISM below 50 and falling -> Short HY
    library.append((
        "ISM <50 and falling: Short HY",
        ConditionSet([
            Condition("ISM", Operator.LT, 50),
            Condition("ISM_MOM_3M", Operator.LT, 0),
        ], name="ISM <50 falling"),
        STRATEGY_LIBRARY["short_HY"],
    ))

    # 3. VIX > 25 -> Long HY (mean reversion)
    library.append((
        "VIX >25: Long HY (vol mean reversion)",
        ConditionSet([
            Condition("VIX", Operator.GT, 25),
        ], name="VIX >25"),
        STRATEGY_LIBRARY["long_HY"],
    ))

    # 4. VIX < 15 -> Short HY (complacency)
    library.append((
        "VIX <15: Short HY (complacency)",
        ConditionSet([
            Condition("VIX", Operator.LT, 15),
        ], name="VIX <15"),
        STRATEGY_LIBRARY["short_HY"],
    ))

    # 5. Curve inverted -> Up in quality (long BB / short CCC)
    library.append((
        "Curve inverted: Up in quality (BB vs CCC)",
        ConditionSet([
            Condition("CURVE_2S10S", Operator.LT, 0),
        ], name="2s10s inverted"),
        STRATEGY_LIBRARY["long_BB_short_CCC"],
    ))

    # 6. HY spread >1 Z-score wide -> Long HY
    library.append((
        "HY Z-score >1 (wide): Long HY",
        ConditionSet([
            Condition("US_HY_ZSCORE", Operator.GT, 1.0),
        ], name="HY Z >1"),
        STRATEGY_LIBRARY["long_HY"],
    ))

    # 7. HY spread <-1 Z-score tight -> Short HY
    library.append((
        "HY Z-score <-1 (tight): Short HY",
        ConditionSet([
            Condition("US_HY_ZSCORE", Operator.LT, -1.0),
        ], name="HY Z <-1"),
        STRATEGY_LIBRARY["short_HY"],
    ))

    # 8. EUR HY wide vs US -> Long EUR / Short US
    library.append((
        "EUR/US HY ratio >1.1: Long EUR/Short US HY",
        ConditionSet([
            Condition("EUR_US_HY_RATIO", Operator.GT, 1.10),
        ], name="EUR HY rich vs US"),
        STRATEGY_LIBRARY["long_EUR_short_US_HY"],
    ))

    # 9. SPX drawdown > 10% -> Long HY (contrarian)
    library.append((
        "SPX drawdown >10%: Long HY (contrarian)",
        ConditionSet([
            Condition("SPX_DRAWDOWN", Operator.LT, -10),
        ], name="SPX DD >10%"),
        STRATEGY_LIBRARY["long_HY"],
    ))

    # 10. VIX term structure in backwardation + VIX >20 -> Short HY
    library.append((
        "VIX backwardation + VIX>20: Short HY",
        ConditionSet([
            Condition("VIX_TERM", Operator.GT, 1.0),
            Condition("VIX", Operator.GT, 20),
        ], name="VIX backwardation"),
        STRATEGY_LIBRARY["short_HY"],
    ))

    # 11. ISM >55 + curve positive -> Down in quality
    library.append((
        "ISM >55 + positive curve: Down in quality (CCC vs BB)",
        ConditionSet([
            Condition("ISM", Operator.GT, 55),
            Condition("CURVE_2S10S", Operator.GT, 0),
        ], name="ISM >55 + pos curve"),
        STRATEGY_LIBRARY["long_CCC_short_BB"],
    ))

    # 12. CCC/BB ratio Z-score > 1.5 -> Down in quality (CCC cheap)
    library.append((
        "CCC/BB ratio very high (CCC cheap): Down in quality",
        ConditionSet([
            Condition("CCC_BB_RATIO", Operator.GT, 5.0),
        ], name="CCC/BB >5x"),
        STRATEGY_LIBRARY["long_CCC_short_BB"],
    ))

    # 13. SLOOS tightening >20 -> Short HY
    library.append((
        "SLOOS tightening >20%: Short HY",
        ConditionSet([
            Condition("SLOOS", Operator.GT, 20),
        ], name="SLOOS tight >20"),
        STRATEGY_LIBRARY["short_HY"],
    ))

    # 14. BTP-Bund >200bps -> Long EUR HY (reversion)
    library.append((
        "BTP-Bund >200bps: Long EUR HY (periphery stress reversion)",
        ConditionSet([
            Condition("BTP_BUND", Operator.GT, 200),
        ], name="BTP-Bund >200bp"),
        STRATEGY_LIBRARY["long_EUR_HY"],
    ))

    # 15. SPX up >10% in 3M + VIX <18 -> Long BB / Short CCC (complacency, go up)
    library.append((
        "SPX rally + low vol: Up in quality",
        ConditionSet([
            Condition("SPX_RET_63D", Operator.GT, 10),
            Condition("VIX", Operator.LT, 18),
        ], name="SPX rally + low vol"),
        STRATEGY_LIBRARY["long_BB_short_CCC"],
    ))

    return library


# =============================================================================
# ANALYTICS & REPORTING
# =============================================================================


def print_backtest_report(result: BacktestResult, verbose: bool = True):
    """Print formatted backtest results."""
    r = result

    print(f"\n  {'=' * 80}")
    print(f"  {r.name}")
    print(f"  {'=' * 80}")
    print(f"  Strategy: {r.strategy.description}")
    print(f"  Conditions: {r.conditions}")
    print(f"  Holding Period: {r.strategy.holding_period} days | Carry: {r.strategy.carry_bps:+.0f} bps/yr")

    print(f"\n  PERFORMANCE:")
    print(f"  {'Signal days':20s}: {r.n_signals:>6d}  ({r.pct_time_in_signal:.1f}% of time)")
    print(f"  {'Trades':20s}: {r.n_trades:>6d}")
    print(f"  {'Hit Rate':20s}: {r.hit_rate:>6.1f}%")
    print(f"  {'Avg Return':20s}: {r.avg_return_bps:>+6.1f} bps")
    print(f"  {'Median Return':20s}: {r.median_return_bps:>+6.1f} bps")
    print(f"  {'Total Return':20s}: {r.total_return_bps:>+6.0f} bps")
    print(f"  {'Sharpe (per trade)':20s}: {r.sharpe:>6.2f}")
    print(f"  {'Max Drawdown':20s}: {r.max_drawdown_bps:>+6.0f} bps")
    print(f"  {'Win Avg':20s}: {r.win_avg_bps:>+6.1f} bps")
    print(f"  {'Loss Avg':20s}: {r.loss_avg_bps:>+6.1f} bps")
    print(f"  {'Profit Factor':20s}: {r.profit_factor:>6.2f}x")

    # Quality rating
    if r.n_trades < 10:
        quality = "INSUFFICIENT DATA"
    elif r.sharpe > 0.5 and r.hit_rate > 55 and r.profit_factor > 1.5:
        quality = "STRONG SIGNAL"
    elif r.sharpe > 0.2 and r.hit_rate > 50 and r.profit_factor > 1.0:
        quality = "MODERATE SIGNAL"
    elif r.sharpe > 0 and r.profit_factor > 0.8:
        quality = "WEAK SIGNAL"
    else:
        quality = "NO EDGE"

    print(f"  {'Signal Quality':20s}: {quality}")

    if verbose and len(r.trades) > 0:
        # Best/worst trades
        best = r.trades.nlargest(3, "total_pnl_bps")
        worst = r.trades.nsmallest(3, "total_pnl_bps")

        print(f"\n  Top 3 Wins:")
        for _, t in best.iterrows():
            print(f"    {t['entry_date'].strftime('%Y-%m-%d')} -> {t['exit_date'].strftime('%Y-%m-%d')} | {t['total_pnl_bps']:>+6.0f}bps (spread: {t['spread_pnl_bps']:>+.0f}, carry: {t['carry_bps']:>+.0f})")

        print(f"  Bottom 3 Losses:")
        for _, t in worst.iterrows():
            print(f"    {t['entry_date'].strftime('%Y-%m-%d')} -> {t['exit_date'].strftime('%Y-%m-%d')} | {t['total_pnl_bps']:>+6.0f}bps (spread: {t['spread_pnl_bps']:>+.0f}, carry: {t['carry_bps']:>+.0f})")

        # By year
        r.trades["year"] = r.trades["entry_date"].dt.year
        yearly = r.trades.groupby("year").agg(
            n_trades=("total_pnl_bps", "count"),
            avg_ret=("total_pnl_bps", "mean"),
            total_ret=("total_pnl_bps", "sum"),
            hit_rate=("win", "mean"),
        )
        print(f"\n  Annual Breakdown:")
        print(f"  {'Year':>6s} {'Trades':>7s} {'Avg':>8s} {'Total':>8s} {'Hit%':>6s}")
        for year, row in yearly.iterrows():
            print(f"  {year:>6d} {row['n_trades']:>7.0f} {row['avg_ret']:>+7.1f} {row['total_ret']:>+7.0f} {row['hit_rate']*100:>5.0f}%")


def print_library_summary(all_results: List[BacktestResult]):
    """Print summary comparison of all backtest results."""
    print("\n" + "=" * 120)
    print("  BACKTEST LIBRARY - SUMMARY COMPARISON")
    print("=" * 120)
    print(f"\n  {'#':>3s} {'Backtest':<55s} {'Trades':>7s} {'Hit%':>6s} {'Avg(bp)':>8s} {'Total':>8s} {'Sharpe':>7s} {'PF':>6s} {'Quality':<15s}")
    print("  " + "-" * 118)

    for i, r in enumerate(all_results, 1):
        if r.n_trades < 10:
            q = "INSUFF DATA"
        elif r.sharpe > 0.5 and r.hit_rate > 55:
            q = "STRONG"
        elif r.sharpe > 0.2 and r.hit_rate > 50:
            q = "MODERATE"
        elif r.sharpe > 0:
            q = "WEAK"
        else:
            q = "NO EDGE"

        print(
            f"  {i:>3d} {r.name:<55s} {r.n_trades:>7d} {r.hit_rate:>5.1f}% "
            f"{r.avg_return_bps:>+7.1f} {r.total_return_bps:>+7.0f} "
            f"{r.sharpe:>+6.2f} {r.profit_factor:>5.2f}x {q:<15s}"
        )

    print("  " + "-" * 118)

    # Top signals
    ranked = sorted(all_results, key=lambda r: r.sharpe if r.n_trades >= 10 else -999, reverse=True)
    print("\n  TOP 5 SIGNALS (by Sharpe):")
    for i, r in enumerate(ranked[:5], 1):
        if r.n_trades < 10:
            continue
        print(f"  {i}. {r.name} | Sharpe={r.sharpe:+.2f} Hit={r.hit_rate:.0f}% Avg={r.avg_return_bps:+.0f}bp")

    print("\n  BOTTOM 5 SIGNALS:")
    for i, r in enumerate(ranked[-5:], 1):
        if r.n_trades < 3:
            continue
        print(f"  {i}. {r.name} | Sharpe={r.sharpe:+.2f} Hit={r.hit_rate:.0f}% Avg={r.avg_return_bps:+.0f}bp")

    print("\n" + "=" * 120)


# =============================================================================
# VISUALIZATION
# =============================================================================


def plot_backtest_results(all_results: List[BacktestResult], top_n: int = 6):
    """Plot dashboard for top backtest results."""
    # Filter to results with enough trades
    valid = [r for r in all_results if r.n_trades >= 5]
    if not valid:
        print("  No valid backtests to plot.")
        return

    # Sort by Sharpe
    valid.sort(key=lambda r: r.sharpe, reverse=True)
    top = valid[:top_n]

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "CREDIT BACKTEST ENGINE - RESULTS",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(all_results)} strategies tested | {HISTORY_YEARS}yr history",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.06)

    # --- Panel 1: Sharpe Comparison ---
    ax1 = fig.add_subplot(gs[0, 0])
    names = [r.name[:35] for r in valid]
    sharpes = [r.sharpe for r in valid]
    colors = ["#2ecc71" if s > 0.3 else "#f39c12" if s > 0 else "#e74c3c" for s in sharpes]
    ax1.barh(range(len(names)), sharpes, color=colors, edgecolor="white")
    ax1.set_yticks(range(len(names)))
    ax1.set_yticklabels(names, fontsize=6)
    ax1.axvline(0, color="black", linewidth=0.8)
    ax1.set_title("Sharpe Ratio by Strategy", fontweight="bold", fontsize=10)
    ax1.set_xlabel("Sharpe (per trade)")

    # --- Panel 2: Hit Rate vs Avg Return ---
    ax2 = fig.add_subplot(gs[0, 1])
    for r in valid:
        c = "#2ecc71" if r.sharpe > 0.2 else "#e74c3c" if r.sharpe < 0 else "#f39c12"
        ax2.scatter(r.hit_rate, r.avg_return_bps, color=c, s=max(r.n_trades, 20), alpha=0.7, edgecolors="white")
        if r in top[:3]:
            ax2.annotate(r.name[:20], (r.hit_rate, r.avg_return_bps), fontsize=6, alpha=0.7)
    ax2.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax2.axvline(50, color="gray", linewidth=0.5, linestyle="--")
    ax2.set_xlabel("Hit Rate (%)")
    ax2.set_ylabel("Avg Return (bps)")
    ax2.set_title("Hit Rate vs Average Return", fontweight="bold", fontsize=10)
    ax2.grid(True, alpha=0.3)

    # --- Panel 3: Profit Factor ---
    ax3 = fig.add_subplot(gs[0, 2])
    pf_names = [r.name[:30] for r in valid]
    pfs = [min(r.profit_factor, 5.0) for r in valid]  # cap at 5 for display
    colors_pf = ["#2ecc71" if p > 1.5 else "#f39c12" if p > 1.0 else "#e74c3c" for p in pfs]
    ax3.barh(range(len(pf_names)), pfs, color=colors_pf, edgecolor="white")
    ax3.set_yticks(range(len(pf_names)))
    ax3.set_yticklabels(pf_names, fontsize=6)
    ax3.axvline(1.0, color="red", linewidth=0.8, linestyle="--", label="Breakeven")
    ax3.set_title("Profit Factor (Gross Wins / Gross Losses)", fontweight="bold", fontsize=10)
    ax3.legend(fontsize=7)

    # --- Panels 4-6: Top 3 equity curves ---
    for i, r in enumerate(top[:3]):
        ax = fig.add_subplot(gs[1, i])
        if len(r.trades) > 0:
            cumret = r.trades["total_pnl_bps"].cumsum()
            ax.plot(r.trades["entry_date"], cumret.values, color="#2c3e50", linewidth=1.2)
            ax.fill_between(r.trades["entry_date"], 0, cumret.values,
                            where=cumret > 0, alpha=0.1, color="green")
            ax.fill_between(r.trades["entry_date"], 0, cumret.values,
                            where=cumret < 0, alpha=0.1, color="red")
            ax.axhline(0, color="gray", linewidth=0.5)
            ax.set_title(f"#{i+1}: {r.name[:40]}\nSharpe={r.sharpe:.2f} Hit={r.hit_rate:.0f}% n={r.n_trades}",
                         fontweight="bold", fontsize=8)
            ax.set_ylabel("Cumulative P&L (bps)")
            ax.grid(True, alpha=0.3)

    # --- Panels 7-9: Top 3 return distributions ---
    for i, r in enumerate(top[:3]):
        ax = fig.add_subplot(gs[2, i])
        if len(r.trades) > 3:
            returns = r.trades["total_pnl_bps"]
            ax.hist(returns, bins=min(20, len(returns) // 2 + 1), color="#3498db",
                    edgecolor="white", alpha=0.7)
            ax.axvline(0, color="black", linewidth=0.8)
            ax.axvline(returns.mean(), color="red", linewidth=1.2, linestyle="--",
                       label=f"Mean: {returns.mean():+.0f}bp")
            ax.axvline(returns.median(), color="orange", linewidth=1.0, linestyle=":",
                       label=f"Median: {returns.median():+.0f}bp")
            ax.set_title(f"Return Distribution: {r.name[:35]}", fontweight="bold", fontsize=8)
            ax.set_xlabel("Trade P&L (bps)")
            ax.legend(fontsize=7)
            ax.grid(True, alpha=0.3)

    out_dir = Path(__file__).resolve().parent.parent / "outputs" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(out_dir / "credit_backtest_results.png"), dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: credit_backtest_results.png")
    plt.close()


# =============================================================================
# CUSTOM BACKTEST BUILDER (for interactive use)
# =============================================================================


def custom_backtest(
    dm: DataManager,
    conditions: List[Tuple[str, str, float]],
    strategy_key: str = "long_HY",
    holding_days: int = 63,
    name: str = "Custom",
) -> BacktestResult:
    """
    Quick custom backtest builder.

    Args:
        dm: DataManager with loaded data
        conditions: list of (series, operator_str, value) tuples
            operator_str: ">", ">=", "<", "<=", "==", "cross_above", "cross_below"
        strategy_key: key from STRATEGY_LIBRARY
        holding_days: holding period in trading days
        name: display name

    Example:
        custom_backtest(dm, [("ISM", ">", 50), ("VIX", ">", 25)], "long_HY", 63)
    """
    op_map = {
        ">": Operator.GT, ">=": Operator.GTE, "<": Operator.LT,
        "<=": Operator.LTE, "==": Operator.EQ,
        "cross_above": Operator.CROSS_ABOVE, "cross_below": Operator.CROSS_BELOW,
    }

    conds = []
    for series, op_str, val in conditions:
        op = op_map.get(op_str, Operator.GT)
        conds.append(Condition(series, op, val))

    cond_set = ConditionSet(conds, name=name)
    strategy = STRATEGY_LIBRARY.get(strategy_key, STRATEGY_LIBRARY["long_HY"])

    # Override holding period
    strategy = Strategy(
        name=strategy.name, description=strategy.description,
        long_leg=strategy.long_leg, short_leg=strategy.short_leg,
        holding_period=holding_days,
        long_weight=strategy.long_weight, short_weight=strategy.short_weight,
        carry_bps=strategy.carry_bps,
    )

    return run_backtest(dm.derived, cond_set, strategy)


# =============================================================================
# MAIN
# =============================================================================


def main():
    print("\n" + "=" * 70)
    print("  CREDIT BACKTEST ENGINE")
    print("  Conditional Macro-Credit Strategy Tester")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  History: {HISTORY_YEARS} years")
    print()

    # 1. Load data
    dm = DataManager()
    dm.load()

    # 2. Build backtest library
    print("\n  Building backtest library...")
    library = build_backtest_library()
    print(f"  {len(library)} pre-built backtests defined")

    # 3. Run all backtests
    print("\n  Running backtests...")
    all_results = []
    for name, conditions, strategy in library:
        result = run_backtest(dm.derived, conditions, strategy)
        all_results.append(result)
        status = "OK" if result.n_trades > 0 else "NO TRADES"
        print(f"    [{status:>9s}] {name:55s} | n={result.n_trades:>3d} Sharpe={result.sharpe:>+.2f}")

    # 4. Print detailed results for top strategies
    ranked = sorted(all_results, key=lambda r: r.sharpe if r.n_trades >= 5 else -999, reverse=True)
    print("\n  DETAILED RESULTS FOR TOP 5 STRATEGIES:")
    for r in ranked[:5]:
        if r.n_trades >= 5:
            print_backtest_report(r, verbose=True)

    # 5. Summary comparison
    print_library_summary(all_results)

    # 6. Visualization
    print("\n  Generating charts...")
    plot_backtest_results(all_results)

    # 7. Save results
    summary_rows = []
    for r in all_results:
        summary_rows.append({
            "backtest": r.name,
            "n_trades": r.n_trades,
            "hit_rate": r.hit_rate,
            "avg_return_bps": r.avg_return_bps,
            "total_return_bps": r.total_return_bps,
            "sharpe": r.sharpe,
            "max_drawdown_bps": r.max_drawdown_bps,
            "profit_factor": r.profit_factor,
            "pct_time_in_signal": r.pct_time_in_signal,
        })
    out_dir = Path(__file__).resolve().parent.parent / "outputs" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary_rows).to_csv(str(out_dir / "credit_backtest_summary.csv"), index=False)
    print(f"  Summary saved: credit_backtest_summary.csv")

    # 8. Print available series for custom backtests
    print(f"\n  AVAILABLE SERIES FOR CUSTOM BACKTESTS ({len(dm.available())}):")
    for i, s in enumerate(dm.available()):
        print(f"    {s}", end="")
        if (i + 1) % 6 == 0:
            print()
    print()

    print(f"\n  CUSTOM BACKTEST EXAMPLE:")
    print(f"    from analytics.credit_backtest_engine import DataManager, custom_backtest, print_backtest_report")
    print(f"    dm = DataManager(); dm.load()")
    print(f"    result = custom_backtest(dm, [('ISM', '>', 50), ('VIX', '<', 20)], 'long_HY', 63)")
    print(f"    print_backtest_report(result)")

    print("\n  DONE.\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Credit Backtest Engine -- macro-credit strategy tester")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of console report")
    args = parser.parse_args()
    main()
