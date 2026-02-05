"""
Options Market Scanner
Scans for high probability options plays
Focuses on defined risk strategies with high R:R
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from loguru import logger

from core.data_cache import get_data_cache

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

from .base_scanner import BaseScanner
from core.models import Signal, MarketType, SignalType


class OptionsScanner(BaseScanner):
    """
    Options scanner for high R:R plays.

    Focus on:
    - Cheap OTM calls/puts on momentum stocks
    - Earnings plays (long straddles/strangles)
    - Weekly options for short-term moves
    - Defined risk spreads

    With $3k capital, focus on:
    - Single leg options under $200
    - Debit spreads with max loss defined
    - High conviction directional bets
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("OptionsScanner", MarketType.OPTIONS, config)

        # Stocks with liquid options
        self.default_watchlist = [
            # High volume options
            'SPY', 'QQQ', 'IWM', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META',
            'NVDA', 'AMD', 'TSLA', 'NFLX',
            # Volatile / meme stocks with options
            'GME', 'AMC', 'PLTR', 'SOFI', 'RIVN', 'LCID',
            # Biotech
            'MRNA', 'BNTX',
            # Banks (for Fed moves)
            'JPM', 'BAC', 'GS', 'MS',
            # Energy
            'XOM', 'CVX', 'OXY',
            # ETFs
            'XLF', 'XLE', 'XLK', 'GLD', 'SLV', 'USO'
        ]

        self.max_option_price = 200  # Max $200 per contract
        self.min_days_to_expiry = 5
        self.max_days_to_expiry = 45

    async def get_universe(self) -> List[str]:
        """Get options-eligible stocks to scan"""
        return self.default_watchlist

    async def fetch_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch stock data for options analysis via shared cache"""
        cache = get_data_cache()
        return await cache.get_history(symbol, 'equity', '3mo', '1d')

    async def analyze(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Analyze for options opportunities"""
        if len(data) < 30:
            return None

        signals = []

        # Strategy 1: Momentum Call/Put
        momentum_signal = await self._check_momentum_option(symbol, data)
        if momentum_signal:
            signals.append(momentum_signal)

        # Strategy 2: Breakout Option Play
        breakout_signal = await self._check_breakout_option(symbol, data)
        if breakout_signal:
            signals.append(breakout_signal)

        # Strategy 3: Oversold Bounce Call
        bounce_signal = await self._check_bounce_option(symbol, data)
        if bounce_signal:
            signals.append(bounce_signal)

        # Strategy 4: Volatility Crush (post-earnings)
        # vol_signal = await self._check_vol_play(symbol, data)
        # if vol_signal:
        #     signals.append(vol_signal)

        if signals:
            return max(signals, key=lambda s: s.confidence * s.risk_reward_ratio)

        return None

    async def _get_option_chain(self, symbol: str, data: pd.DataFrame) -> Optional[Dict]:
        """Get options chain data via shared cache"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)

            # Get expiration dates
            expirations = ticker.options

            if not expirations:
                return None

            # Find appropriate expiration (2-4 weeks out)
            today = datetime.now().date()
            target_expiry = None

            for exp in expirations:
                exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
                days_to_exp = (exp_date - today).days

                if self.min_days_to_expiry <= days_to_exp <= self.max_days_to_expiry:
                    target_expiry = exp
                    break

            if not target_expiry:
                return None

            # Get chain
            chain = ticker.option_chain(target_expiry)

            return {
                'calls': chain.calls,
                'puts': chain.puts,
                'expiry': target_expiry,
                'days_to_expiry': (datetime.strptime(target_expiry, '%Y-%m-%d').date() - today).days
            }

        except Exception as e:
            logger.debug(f"Error getting options chain for {symbol}: {e}")
            return None

    async def _check_momentum_option(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Find momentum plays with cheap options"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']
            volume = data['volume']

            # Calculate indicators
            data['rsi'] = ta.rsi(close, length=14)
            data['ema20'] = ta.ema(close, length=20)
            data['ema50'] = ta.ema(close, length=50)
            data['atr'] = ta.atr(high, low, close, length=14)

            current = data.iloc[-1]
            price = current['close']
            rsi = current['rsi']
            atr = current['atr']

            # Strong momentum conditions
            uptrend = current['ema20'] > current['ema50']
            strong_momentum = 55 < rsi < 75
            above_ema = price > current['ema20']

            # Volume confirmation
            avg_volume = volume[-20:].mean()
            good_volume = current['volume'] > avg_volume * 1.2

            if uptrend and strong_momentum and above_ema and good_volume:
                # Get options chain
                chain = await self._get_option_chain(symbol, data)

                if not chain:
                    return None

                calls = chain['calls']
                days_to_exp = chain['days_to_expiry']

                # Find slightly OTM call
                otm_calls = calls[calls['strike'] > price * 1.02]
                otm_calls = otm_calls[otm_calls['strike'] < price * 1.10]

                if otm_calls.empty:
                    return None

                # Find affordable option with good volume
                affordable = otm_calls[otm_calls['lastPrice'] * 100 <= self.max_option_price]
                affordable = affordable[affordable['volume'] > 100]

                if affordable.empty:
                    return None

                # Select best option (closest to money that's affordable)
                best_option = affordable.iloc[0]
                strike = best_option['strike']
                premium = best_option['lastPrice']

                # Calculate R:R (max loss is premium, potential gain is much higher)
                entry_cost = premium * 100
                target_stock_price = price + (2 * atr)
                target_option_value = max(0, target_stock_price - strike) + 0.5  # Intrinsic + time value estimate

                potential_gain = (target_option_value - premium) * 100
                rr_ratio = potential_gain / entry_cost if entry_cost > 0 else 0

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.OPTIONS,
                        signal_type=SignalType.BUY,
                        confidence=0.68,
                        entry_price=premium,
                        target_price=target_option_value,
                        stop_loss=0,  # Max loss is premium paid
                        risk_reward_ratio=rr_ratio,
                        source="options_momentum_call",
                        metadata={
                            'strategy': 'momentum_call',
                            'option_type': 'call',
                            'strike': strike,
                            'expiry': chain['expiry'],
                            'days_to_expiry': days_to_exp,
                            'stock_price': price,
                            'premium': premium,
                            'contract_cost': entry_cost,
                            'rsi': rsi
                        }
                    )

        except Exception as e:
            logger.debug(f"Momentum option check error for {symbol}: {e}")

        return None

    async def _check_breakout_option(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Find breakout plays for options"""
        try:
            close = data['close']
            high = data['high']
            low = data['low']

            # 20-day range
            range_high = high[-20:].max()
            range_low = low[-20:].min()

            current = data.iloc[-1]
            price = current['close']

            # About to break out (near highs)
            near_breakout = price > range_high * 0.98

            if near_breakout:
                if PANDAS_TA_AVAILABLE:
                    data['atr'] = ta.atr(high, low, close, length=14)
                    atr = data['atr'].iloc[-1]
                else:
                    atr = (high - low).mean()

                chain = await self._get_option_chain(symbol, data)

                if not chain:
                    return None

                calls = chain['calls']
                days_to_exp = chain['days_to_expiry']

                # ATM or slightly OTM call for breakout
                atm_calls = calls[calls['strike'] >= price * 0.99]
                atm_calls = atm_calls[atm_calls['strike'] <= price * 1.05]

                if atm_calls.empty:
                    return None

                affordable = atm_calls[atm_calls['lastPrice'] * 100 <= self.max_option_price]

                if affordable.empty:
                    return None

                best_option = affordable.iloc[0]
                strike = best_option['strike']
                premium = best_option['lastPrice']

                entry_cost = premium * 100
                target_move = range_high - range_low  # Measured move
                target_stock_price = range_high + target_move
                target_option_value = max(0, target_stock_price - strike) + 0.3

                potential_gain = (target_option_value - premium) * 100
                rr_ratio = potential_gain / entry_cost if entry_cost > 0 else 0

                if rr_ratio >= 2.5:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.OPTIONS,
                        signal_type=SignalType.BUY,
                        confidence=0.65,
                        entry_price=premium,
                        target_price=target_option_value,
                        stop_loss=0,
                        risk_reward_ratio=rr_ratio,
                        source="options_breakout_call",
                        metadata={
                            'strategy': 'breakout_call',
                            'option_type': 'call',
                            'strike': strike,
                            'expiry': chain['expiry'],
                            'days_to_expiry': days_to_exp,
                            'stock_price': price,
                            'range_high': range_high,
                            'premium': premium
                        }
                    )

        except Exception as e:
            logger.debug(f"Breakout option check error for {symbol}: {e}")

        return None

    async def _check_bounce_option(self, symbol: str, data: pd.DataFrame) -> Optional[Signal]:
        """Find oversold bounce plays"""
        if not PANDAS_TA_AVAILABLE:
            return None

        try:
            close = data['close']
            high = data['high']
            low = data['low']

            data['rsi'] = ta.rsi(close, length=14)
            data['bb_lower'] = ta.bbands(close, length=20)['BBL_20_2.0']
            data['atr'] = ta.atr(high, low, close, length=14)

            current = data.iloc[-1]
            price = current['close']
            rsi = current['rsi']
            bb_lower = current['bb_lower']
            atr = current['atr']

            # Oversold conditions
            oversold = rsi < 30
            at_support = price < bb_lower * 1.02

            if oversold and at_support:
                chain = await self._get_option_chain(symbol, data)

                if not chain:
                    return None

                calls = chain['calls']
                days_to_exp = chain['days_to_expiry']

                # Slightly ITM or ATM call for bounce
                itm_calls = calls[calls['strike'] <= price * 1.02]
                itm_calls = itm_calls[itm_calls['strike'] >= price * 0.95]

                if itm_calls.empty:
                    return None

                affordable = itm_calls[itm_calls['lastPrice'] * 100 <= self.max_option_price]

                if affordable.empty:
                    return None

                # Get highest delta (most ITM affordable)
                best_option = affordable.iloc[-1]
                strike = best_option['strike']
                premium = best_option['lastPrice']

                entry_cost = premium * 100
                target_stock_price = price + (2.5 * atr)  # Mean reversion target
                target_option_value = max(0, target_stock_price - strike) + 0.5

                potential_gain = (target_option_value - premium) * 100
                rr_ratio = potential_gain / entry_cost if entry_cost > 0 else 0

                if rr_ratio >= 2.0:
                    return Signal(
                        symbol=symbol,
                        market_type=MarketType.OPTIONS,
                        signal_type=SignalType.BUY,
                        confidence=0.62,
                        entry_price=premium,
                        target_price=target_option_value,
                        stop_loss=0,
                        risk_reward_ratio=rr_ratio,
                        source="options_bounce_call",
                        metadata={
                            'strategy': 'oversold_bounce',
                            'option_type': 'call',
                            'strike': strike,
                            'expiry': chain['expiry'],
                            'days_to_expiry': days_to_exp,
                            'stock_price': price,
                            'rsi': rsi,
                            'premium': premium
                        }
                    )

        except Exception as e:
            logger.debug(f"Bounce option check error for {symbol}: {e}")

        return None
