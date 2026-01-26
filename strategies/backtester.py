"""
Backtesting Engine
Tests trading strategies against historical data to prove edge
"""
import asyncio
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False


def _calc_rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Manual RSI calculation - no pandas_ta needed"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1/length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_bbands(series: pd.Series, length: int = 20, std: float = 2.0) -> Dict:
    """Manual Bollinger Bands calculation - no pandas_ta needed"""
    mid = series.rolling(length).mean()
    band_std = series.rolling(length).std()
    upper = mid + (band_std * std)
    lower = mid - (band_std * std)
    return {f'BBU_{length}_{std}': upper, f'BBM_{length}_{std}': mid, f'BBL_{length}_{std}': lower}


@dataclass
class BacktestTrade:
    """A single trade in a backtest"""
    symbol: str
    entry_date: datetime
    exit_date: datetime
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    strategy: str
    hold_days: int


@dataclass
class BacktestResult:
    """Results from a backtest run"""
    strategy: str
    symbol_universe: str
    period: str
    total_trades: int
    winners: int
    losers: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    total_pnl_pct: float
    max_drawdown_pct: float
    avg_hold_days: float
    sharpe_ratio: float
    expectancy: float  # avg $ per trade
    trades: List[BacktestTrade] = field(default_factory=list)

    def summary(self) -> str:
        """Human readable summary"""
        edge = "YES" if self.profit_factor > 1.2 and self.win_rate > 0.40 else "NO"
        return f"""
{'='*60}
BACKTEST: {self.strategy} ({self.symbol_universe})
Period: {self.period}
{'='*60}
Total Trades:     {self.total_trades}
Win Rate:         {self.win_rate:.1%}
Avg Winner:       +{self.avg_win_pct:.2f}%
Avg Loser:        {self.avg_loss_pct:.2f}%
Profit Factor:    {self.profit_factor:.2f}
Total Return:     {self.total_pnl_pct:+.2f}%
Max Drawdown:     {self.max_drawdown_pct:.2f}%
Avg Hold Time:    {self.avg_hold_days:.1f} days
Sharpe Ratio:     {self.sharpe_ratio:.2f}
Expectancy/Trade: {self.expectancy:+.2f}%

EDGE DETECTED: {edge}
{'='*60}
"""


# ==================== Retail-Heavy Universes ====================

RETAIL_UNIVERSES = {
    "meme_stocks": {
        "name": "Meme / Reddit Stocks",
        "why": "Extreme retail participation, emotional swings, social media driven",
        "symbols": [
            'GME', 'AMC', 'PLTR', 'SOFI', 'BB', 'BBBY', 'WISH',
            'CLOV', 'RIVN', 'LCID', 'NIO', 'MARA', 'RIOT',
            'DKNG', 'HOOD', 'SNAP', 'PINS'
        ]
    },
    "popular_options": {
        "name": "High Retail Options Volume",
        "why": "Retail traders love weekly options on these - creates gamma squeezes",
        "symbols": [
            'SPY', 'QQQ', 'TSLA', 'AAPL', 'NVDA', 'AMD', 'META',
            'AMZN', 'MSFT', 'GOOGL', 'NFLX', 'COIN', 'SQ'
        ]
    },
    "small_cap_momentum": {
        "name": "Small Cap Momentum",
        "why": "Low institutional coverage, retail-driven pumps and dumps",
        "symbols": [
            'SOFI', 'PLTR', 'MARA', 'RIOT', 'LCID', 'RIVN',
            'JOBY', 'STEM', 'IONQ', 'RKLB', 'DNA', 'OPEN'
        ]
    },
    "crypto": {
        "name": "Crypto (Retail Dominated)",
        "why": "Most retail of all markets, 24/7 emotional trading, social media driven",
        "symbols": [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'DOGE-USD',
            'ADA-USD', 'XRP-USD', 'AVAX-USD', 'MATIC-USD'
        ]
    },
    "etf_retail": {
        "name": "Popular Retail ETFs",
        "why": "Retail traders use these for broad bets, high options volume",
        "symbols": [
            'SPY', 'QQQ', 'IWM', 'ARKK', 'TQQQ', 'SQQQ',
            'XLE', 'XLF', 'GLD', 'SLV', 'USO', 'TLT'
        ]
    }
}


# ==================== Strategy Definitions ====================

class Strategies:
    """Trading strategies to backtest"""

    @staticmethod
    def momentum_breakout(data: pd.DataFrame, params: Dict = None) -> pd.DataFrame:
        """
        Momentum breakout - buy when price breaks 20-day high with volume.
        Retail edge: Retail traders chase breakouts late, we get in early.
        """
        params = params or {}
        lookback = params.get('lookback', 20)
        vol_mult = params.get('volume_multiplier', 1.5)
        hold_days = params.get('hold_days', 5)

        df = data.copy()
        df['high_20'] = df['high'].rolling(lookback).max().shift(1)
        df['vol_avg'] = df['volume'].rolling(lookback).mean()

        # Entry: price breaks above 20-day high with volume surge
        df['entry'] = (
            (df['close'] > df['high_20']) &
            (df['volume'] > df['vol_avg'] * vol_mult)
        )

        # Exit: hold for N days
        df['hold_days'] = hold_days

        return df

    @staticmethod
    def mean_reversion_oversold(data: pd.DataFrame, params: Dict = None) -> pd.DataFrame:
        """
        Mean reversion - buy when RSI oversold, sell on bounce.
        Retail edge: Retail panic sells at lows, we buy the fear.
        """
        params = params or {}
        rsi_entry = params.get('rsi_entry', 30)
        rsi_exit = params.get('rsi_exit', 50)
        hold_days = params.get('max_hold_days', 10)

        df = data.copy()
        df['rsi'] = ta.rsi(df['close'], length=14) if PANDAS_TA_AVAILABLE else _calc_rsi(df['close'], 14)

        # Entry: RSI below threshold
        df['entry'] = df['rsi'] < rsi_entry

        # Exit: RSI recovers or max hold
        df['exit_signal'] = df['rsi'] > rsi_exit
        df['hold_days'] = hold_days

        return df

    @staticmethod
    def rsi_divergence(data: pd.DataFrame, params: Dict = None) -> pd.DataFrame:
        """
        RSI divergence - price makes new low but RSI makes higher low.
        Retail edge: Retail can't spot divergences, institutions can.
        """
        params = params or {}
        lookback = params.get('lookback', 14)
        hold_days = params.get('hold_days', 7)

        df = data.copy()
        df['rsi'] = ta.rsi(df['close'], length=lookback) if PANDAS_TA_AVAILABLE else _calc_rsi(df['close'], lookback)

        # Find price lows and RSI lows
        df['price_low_5'] = df['close'].rolling(5).min()
        df['rsi_low_5'] = df['rsi'].rolling(5).min()

        # Bullish divergence: price new low, RSI higher low
        df['prev_price_low'] = df['price_low_5'].shift(5)
        df['prev_rsi_low'] = df['rsi_low_5'].shift(5)

        df['entry'] = (
            (df['close'] < df['prev_price_low']) &
            (df['rsi'] > df['prev_rsi_low']) &
            (df['rsi'] < 40)  # Must be relatively oversold
        )

        df['hold_days'] = hold_days

        return df

    @staticmethod
    def volume_spike_reversal(data: pd.DataFrame, params: Dict = None) -> pd.DataFrame:
        """
        Volume spike on red day = institutions buying while retail panics.
        Retail edge: Retail sells on fear volume, smart money accumulates.
        """
        params = params or {}
        vol_spike = params.get('volume_spike', 2.5)
        hold_days = params.get('hold_days', 5)

        df = data.copy()
        df['vol_avg'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_avg']
        df['red_day'] = df['close'] < df['open']
        df['big_drop'] = df['close'].pct_change() < -0.02  # 2%+ drop

        # Entry: massive volume on red day with 2%+ drop
        df['entry'] = (
            (df['vol_ratio'] > vol_spike) &
            df['red_day'] &
            df['big_drop']
        )

        df['hold_days'] = hold_days

        return df

    @staticmethod
    def gap_fade(data: pd.DataFrame, params: Dict = None) -> pd.DataFrame:
        """
        Fade opening gaps - retail FOMO creates gaps that fill.
        Retail edge: Retail chases overnight gaps, gaps tend to fill.
        """
        params = params or {}
        min_gap_pct = params.get('min_gap_pct', 0.03)  # 3% gap
        hold_days = params.get('hold_days', 3)

        df = data.copy()
        df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)

        # Entry: fade gap ups (sell signal) or buy gap downs
        df['entry'] = df['gap'] < -min_gap_pct  # Buy after gap down

        df['hold_days'] = hold_days

        return df

    @staticmethod
    def bollinger_squeeze(data: pd.DataFrame, params: Dict = None) -> pd.DataFrame:
        """
        Bollinger Band squeeze breakout.
        Retail edge: Low volatility -> explosion. Retail enters late.
        """
        params = params or {}
        squeeze_percentile = params.get('squeeze_percentile', 20)
        hold_days = params.get('hold_days', 7)

        df = data.copy()
        # Always use manual calculation to avoid column naming issues
        bb_mid = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        bb_upper = bb_mid + (bb_std * 2.0)
        bb_lower = bb_mid - (bb_std * 2.0)

        df['bb_width'] = (bb_upper - bb_lower) / bb_mid
        df['bb_width_pctile'] = df['bb_width'].rolling(100).rank(pct=True) * 100

        # Entry: squeeze (low width) then breakout above upper band
        df['in_squeeze'] = df['bb_width_pctile'] < squeeze_percentile
        df['squeeze_release'] = df['in_squeeze'].shift(1) & ~df['in_squeeze']
        df['above_mid'] = df['close'] > bb_mid

        df['entry'] = df['squeeze_release'] & df['above_mid']
        df['hold_days'] = hold_days

        return df


# ==================== Backtesting Engine ====================

class BacktestEngine:
    """
    Runs backtests on strategies against historical data.

    Usage:
        engine = BacktestEngine()
        result = engine.run(
            strategy='momentum_breakout',
            universe='meme_stocks',
            period='2y'
        )
        print(result.summary())
    """

    def __init__(self, initial_capital: float = 3000.0):
        self.initial_capital = initial_capital
        self.strategies = {
            'momentum_breakout': Strategies.momentum_breakout,
            'mean_reversion': Strategies.mean_reversion_oversold,
            'rsi_divergence': Strategies.rsi_divergence,
            'volume_spike': Strategies.volume_spike_reversal,
            'gap_fade': Strategies.gap_fade,
            'bollinger_squeeze': Strategies.bollinger_squeeze,
        }

    def fetch_data(self, symbol: str, period: str = "2y") -> Optional[pd.DataFrame]:
        """Fetch historical data for backtesting"""
        if not YFINANCE_AVAILABLE:
            return None

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval="1d")

            if df.empty or len(df) < 60:
                return None

            df.columns = [c.lower() for c in df.columns]
            return df

        except Exception as e:
            logger.debug(f"Fetch error for {symbol}: {e}")
            return None

    def backtest_symbol(
        self,
        symbol: str,
        strategy_fn: Callable,
        data: pd.DataFrame,
        params: Dict = None,
        position_size_pct: float = 0.05
    ) -> List[BacktestTrade]:
        """Run backtest on a single symbol"""
        trades = []

        try:
            # Apply strategy
            signals = strategy_fn(data, params)

            if 'entry' not in signals.columns:
                return trades

            hold_days = signals.get('hold_days', pd.Series(5, index=signals.index))
            if isinstance(hold_days, int):
                default_hold = hold_days
            else:
                default_hold = 5

            in_trade = False
            entry_idx = None
            entry_price = 0

            for i in range(len(signals)):
                if in_trade:
                    days_held = i - entry_idx

                    # Check exit conditions
                    exit_triggered = False

                    # Time-based exit
                    current_hold = signals.iloc[entry_idx].get('hold_days', default_hold)
                    if isinstance(current_hold, (pd.Series,)):
                        current_hold = default_hold
                    if days_held >= current_hold:
                        exit_triggered = True

                    # Signal-based exit
                    if 'exit_signal' in signals.columns:
                        if signals.iloc[i].get('exit_signal', False):
                            exit_triggered = True

                    if exit_triggered:
                        exit_price = signals.iloc[i]['close']
                        pnl_pct = ((exit_price / entry_price) - 1) * 100
                        position_value = self.initial_capital * position_size_pct
                        quantity = position_value / entry_price
                        pnl = (exit_price - entry_price) * quantity

                        trades.append(BacktestTrade(
                            symbol=symbol,
                            entry_date=signals.index[entry_idx],
                            exit_date=signals.index[i],
                            side='buy',
                            entry_price=entry_price,
                            exit_price=exit_price,
                            quantity=quantity,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            strategy=strategy_fn.__name__,
                            hold_days=days_held
                        ))

                        in_trade = False

                elif signals.iloc[i].get('entry', False):
                    in_trade = True
                    entry_idx = i
                    entry_price = signals.iloc[i]['close']

        except Exception as e:
            logger.debug(f"Backtest error for {symbol}: {e}")

        return trades

    def run(
        self,
        strategy: str,
        universe: str = "meme_stocks",
        period: str = "2y",
        params: Dict = None
    ) -> BacktestResult:
        """
        Run a full backtest.

        Args:
            strategy: Strategy name
            universe: Universe key from RETAIL_UNIVERSES
            period: Historical period ('1y', '2y', etc.)
            params: Strategy parameters
        """
        strategy_fn = self.strategies.get(strategy)
        if not strategy_fn:
            raise ValueError(f"Unknown strategy: {strategy}")

        universe_data = RETAIL_UNIVERSES.get(universe, {})
        symbols = universe_data.get('symbols', [])
        universe_name = universe_data.get('name', universe)

        logger.info(f"Backtesting {strategy} on {universe_name} ({len(symbols)} symbols, {period})")

        all_trades = []

        for symbol in symbols:
            data = self.fetch_data(symbol, period)
            if data is None:
                continue

            trades = self.backtest_symbol(symbol, strategy_fn, data, params)
            all_trades.extend(trades)
            if trades:
                logger.info(f"  {symbol}: {len(trades)} trades")

        return self._compile_results(all_trades, strategy, universe_name, period)

    def run_all(self, universe: str = "meme_stocks", period: str = "2y") -> List[BacktestResult]:
        """Run all strategies on a universe"""
        results = []
        for strategy_name in self.strategies:
            result = self.run(strategy_name, universe, period)
            results.append(result)
        return results

    def _compile_results(
        self,
        trades: List[BacktestTrade],
        strategy: str,
        universe: str,
        period: str
    ) -> BacktestResult:
        """Compile trade list into results"""
        if not trades:
            return BacktestResult(
                strategy=strategy,
                symbol_universe=universe,
                period=period,
                total_trades=0,
                winners=0, losers=0,
                win_rate=0, avg_win_pct=0, avg_loss_pct=0,
                profit_factor=0, total_pnl_pct=0,
                max_drawdown_pct=0, avg_hold_days=0,
                sharpe_ratio=0, expectancy=0,
                trades=trades
            )

        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl <= 0]

        gross_profit = sum(t.pnl_pct for t in winners)
        gross_loss = abs(sum(t.pnl_pct for t in losers))

        win_rate = len(winners) / len(trades) if trades else 0
        avg_win = np.mean([t.pnl_pct for t in winners]) if winners else 0
        avg_loss = np.mean([t.pnl_pct for t in losers]) if losers else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        total_pnl = sum(t.pnl_pct for t in trades)
        avg_hold = np.mean([t.hold_days for t in trades])

        # Calculate max drawdown
        cumulative = np.cumsum([t.pnl_pct for t in trades])
        peak = np.maximum.accumulate(cumulative)
        drawdown = cumulative - peak
        max_dd = abs(min(drawdown)) if len(drawdown) > 0 else 0

        # Sharpe ratio (annualized)
        returns = [t.pnl_pct for t in trades]
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252 / max(avg_hold, 1))
        else:
            sharpe = 0

        # Expectancy (avg return per trade)
        expectancy = np.mean([t.pnl_pct for t in trades])

        return BacktestResult(
            strategy=strategy,
            symbol_universe=universe,
            period=period,
            total_trades=len(trades),
            winners=len(winners),
            losers=len(losers),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            profit_factor=profit_factor,
            total_pnl_pct=total_pnl,
            max_drawdown_pct=max_dd,
            avg_hold_days=avg_hold,
            sharpe_ratio=sharpe,
            expectancy=expectancy,
            trades=trades
        )


def run_full_backtest():
    """Run comprehensive backtest across all strategies and universes"""
    engine = BacktestEngine(initial_capital=3000.0)

    print("\n" + "=" * 70)
    print("COMPREHENSIVE BACKTEST - RETAIL MARKET EDGE ANALYSIS")
    print("=" * 70)

    all_results = []

    for universe_key, universe_data in RETAIL_UNIVERSES.items():
        print(f"\n{'─' * 70}")
        print(f"Universe: {universe_data['name']}")
        print(f"Why: {universe_data['why']}")
        print(f"Symbols: {', '.join(universe_data['symbols'][:8])}...")
        print(f"{'─' * 70}")

        results = engine.run_all(universe=universe_key, period="2y")

        for result in results:
            all_results.append(result)
            if result.total_trades > 0:
                edge = "✅ EDGE" if result.profit_factor > 1.2 and result.win_rate > 0.40 else "❌ NO EDGE"
                print(
                    f"  {result.strategy:25s} | "
                    f"Trades: {result.total_trades:4d} | "
                    f"Win: {result.win_rate:5.1%} | "
                    f"PF: {result.profit_factor:5.2f} | "
                    f"Return: {result.total_pnl_pct:+7.1f}% | "
                    f"{edge}"
                )

    # Summary: best strategies
    print("\n" + "=" * 70)
    print("TOP STRATEGIES BY PROFIT FACTOR")
    print("=" * 70)

    profitable = [r for r in all_results if r.total_trades >= 10 and r.profit_factor > 1.0]
    profitable.sort(key=lambda x: x.profit_factor, reverse=True)

    for i, r in enumerate(profitable[:10], 1):
        print(
            f"{i:2d}. {r.strategy:25s} on {r.symbol_universe:30s} | "
            f"PF: {r.profit_factor:.2f} | "
            f"Win: {r.win_rate:.1%} | "
            f"Trades: {r.total_trades}"
        )

    return all_results


# CLI
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backtest Trading Strategies")
    parser.add_argument("--strategy", "-s", type=str, help="Strategy to test")
    parser.add_argument("--universe", "-u", type=str, default="meme_stocks",
                       help="Market universe")
    parser.add_argument("--period", "-p", type=str, default="2y", help="Period")
    parser.add_argument("--all", action="store_true", help="Run all backtests")

    args = parser.parse_args()

    if args.all:
        run_full_backtest()
    elif args.strategy:
        engine = BacktestEngine()
        result = engine.run(args.strategy, args.universe, args.period)
        print(result.summary())
    else:
        run_full_backtest()
