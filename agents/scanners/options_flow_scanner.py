"""
Unusual Options Flow Scanner
Detects unusual options activity that may indicate institutional/informed positioning.

This is our free alternative to Unusual Whales - built using yfinance options chains
(will switch to IB data when connected for real-time flow).

Key Detection Methods:
- Volume/Open Interest ratio: V/OI > 2.0 = fresh positioning, not rolling
- Call/Put volume skew: Extreme ratios indicate directional bets
- Strike concentration: Disproportionate volume at specific strikes = targeted bet
- Sweep detection: Large volume at OTM strikes with low OI = aggressive entry
- Expiry analysis: Near-term heavy volume = event-driven positioning

Why this works:
- Smart money uses options for leverage before catalysts
- Unusual flow often precedes 3-10 day moves
- Combining with our technical signals creates powerful confluence
"""
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from loguru import logger

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from core.base_agent import BaseAgent, AgentMessage
from core.models import Signal, MarketType, SignalType


@dataclass
class UnusualFlow:
    """Represents detected unusual options activity"""
    symbol: str
    flow_type: str              # 'bullish_sweep', 'bearish_sweep', 'call_surge', 'put_surge', 'straddle'
    strike: float
    expiry: str
    days_to_expiry: int
    option_type: str            # 'call' or 'put'
    volume: int
    open_interest: int
    voi_ratio: float            # Volume / Open Interest ratio
    implied_premium: float      # Total premium spent (volume * last price * 100)
    stock_price: float
    otm_pct: float              # How far OTM (%)
    details: Dict[str, Any] = field(default_factory=dict)


class OptionsFlowScanner(BaseAgent):
    """
    Scans for unusual options flow as a signal for upcoming moves.

    Detection logic:
    1. Fetch options chains for watchlist via yfinance
    2. Calculate V/OI ratios across all strikes/expiries
    3. Detect unusual volume concentration
    4. Score and filter for actionable flow signals
    5. Generate buy/sell signals based on flow direction

    Scan frequency: Every 15 minutes during market hours
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__("OptionsFlowScanner", config)
        self.scan_interval = 900  # 15 minutes
        self.last_scan: Optional[datetime] = None
        self.seen_flows: set = set()  # Deduplicate flow alerts

        # Track recent unusual flow for confluence detection
        self.recent_flows: Dict[str, List[UnusualFlow]] = {}
        self.signals_generated: List[Signal] = []

        # Watchlist - liquid options names where flow matters
        self.watchlist = [
            # Mega caps with huge options volume
            'SPY', 'QQQ', 'IWM', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META',
            'NVDA', 'AMD', 'TSLA', 'NFLX',
            # High retail/meme interest (flow signals strongest here)
            'GME', 'AMC', 'PLTR', 'SOFI', 'RIVN', 'LCID', 'HOOD',
            # Crypto-related (correlated with our crypto positions)
            'COIN', 'MARA', 'RIOT',
            # Volatile sectors
            'XLE', 'XLF', 'GLD', 'SLV',
            # Biotech (event-driven flow)
            'MRNA', 'BNTX',
            # Leveraged ETFs (flow = leveraged directional bet)
            'TQQQ', 'SQQQ',
        ]

        # Detection thresholds
        self.min_voi_ratio = 2.0       # Min Volume/OI for "unusual"
        self.min_premium = 50_000      # Min $50k total premium spent
        self.min_volume = 500          # Min contracts traded
        self.max_dte = 45              # Max days to expiry to consider
        self.sweep_voi_threshold = 5.0 # V/OI for sweep detection
        self.call_put_skew = 3.0       # C/P ratio threshold for directional

    async def process(self) -> None:
        """Main scanning loop"""
        if not YFINANCE_AVAILABLE:
            logger.warning("[OptionsFlow] yfinance not available")
            await asyncio.sleep(60)
            return

        # Check scan interval
        if self.last_scan:
            elapsed = (datetime.now() - self.last_scan).seconds
            if elapsed < self.scan_interval:
                await asyncio.sleep(5)
                return

        logger.info("[OptionsFlow] Scanning for unusual options activity...")

        signals_found = 0

        for symbol in self.watchlist:
            try:
                flows = await self._scan_symbol(symbol)

                if flows:
                    # Generate signal from the strongest flow
                    signal = self._generate_signal(symbol, flows)
                    if signal:
                        signals_found += 1
                        self.signals_generated.append(signal)
                        await self._broadcast_signal(signal)

                    # Track for confluence
                    self.recent_flows[symbol] = flows

                # Small delay to avoid hammering yfinance
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.debug(f"[OptionsFlow] Error scanning {symbol}: {e}")
                continue

        # Clean old flows (older than 3 days)
        self._cleanup_old_flows()

        self.last_scan = datetime.now()
        logger.info(f"[OptionsFlow] Scan complete. Unusual flow signals: {signals_found}")

    async def _scan_symbol(self, symbol: str) -> List[UnusualFlow]:
        """Scan a single symbol's options chain for unusual activity"""
        unusual_flows = []

        try:
            ticker = yf.Ticker(symbol)

            # Get current stock price
            hist = ticker.history(period="2d")
            if hist.empty:
                return unusual_flows
            stock_price = hist['Close'].iloc[-1]

            # Get available expirations
            try:
                expirations = ticker.options
            except Exception:
                return unusual_flows

            if not expirations:
                return unusual_flows

            today = datetime.now().date()

            # Scan each expiration within our window
            for exp_str in expirations:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
                dte = (exp_date - today).days

                if dte < 0 or dte > self.max_dte:
                    continue

                try:
                    chain = ticker.option_chain(exp_str)
                except Exception:
                    continue

                # Analyze calls
                call_flows = self._analyze_chain_side(
                    symbol, chain.calls, 'call', stock_price, exp_str, dte
                )
                unusual_flows.extend(call_flows)

                # Analyze puts
                put_flows = self._analyze_chain_side(
                    symbol, chain.puts, 'put', stock_price, exp_str, dte
                )
                unusual_flows.extend(put_flows)

                # Check for straddle/strangle activity (both sides heavy at same strike)
                straddle_flows = self._detect_straddle_activity(
                    symbol, chain.calls, chain.puts, stock_price, exp_str, dte
                )
                unusual_flows.extend(straddle_flows)

                # Rate limit between expirations
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.debug(f"[OptionsFlow] Chain scan error for {symbol}: {e}")

        # Sort by significance (premium spent)
        unusual_flows.sort(key=lambda f: f.implied_premium, reverse=True)

        # Deduplicate - only keep the strongest flow per symbol
        return unusual_flows[:5]

    def _analyze_chain_side(
        self,
        symbol: str,
        chain: pd.DataFrame,
        option_type: str,
        stock_price: float,
        expiry: str,
        dte: int
    ) -> List[UnusualFlow]:
        """Analyze one side (calls or puts) of an options chain"""
        flows = []

        if chain.empty:
            return flows

        for _, row in chain.iterrows():
            try:
                volume = int(row.get('volume', 0) or 0)
                oi = int(row.get('openInterest', 0) or 0)
                last_price = float(row.get('lastPrice', 0) or 0)
                strike = float(row.get('strike', 0))

                # Skip low activity
                if volume < self.min_volume:
                    continue

                # Calculate V/OI ratio
                voi_ratio = volume / max(oi, 1)

                # Calculate total premium
                total_premium = volume * last_price * 100

                # Skip low premium
                if total_premium < self.min_premium:
                    continue

                # Calculate OTM percentage
                if option_type == 'call':
                    otm_pct = ((strike - stock_price) / stock_price) * 100
                else:
                    otm_pct = ((stock_price - strike) / stock_price) * 100

                # Determine flow type
                flow_type = self._classify_flow(
                    voi_ratio, volume, oi, total_premium, otm_pct, option_type, dte
                )

                if flow_type:
                    # Create dedup key
                    flow_key = f"{symbol}_{strike}_{expiry}_{option_type}"
                    if flow_key in self.seen_flows:
                        continue

                    flows.append(UnusualFlow(
                        symbol=symbol,
                        flow_type=flow_type,
                        strike=strike,
                        expiry=expiry,
                        days_to_expiry=dte,
                        option_type=option_type,
                        volume=volume,
                        open_interest=oi,
                        voi_ratio=voi_ratio,
                        implied_premium=total_premium,
                        stock_price=stock_price,
                        otm_pct=otm_pct,
                        details={
                            'last_price': last_price,
                            'bid': float(row.get('bid', 0) or 0),
                            'ask': float(row.get('ask', 0) or 0),
                            'implied_vol': float(row.get('impliedVolatility', 0) or 0),
                        }
                    ))

                    self.seen_flows.add(flow_key)

            except (ValueError, TypeError, KeyError):
                continue

        return flows

    def _classify_flow(
        self,
        voi_ratio: float,
        volume: int,
        oi: int,
        total_premium: float,
        otm_pct: float,
        option_type: str,
        dte: int
    ) -> Optional[str]:
        """Classify the type of unusual flow"""

        # Sweep: Very high V/OI + significant premium at OTM strikes
        # This is the strongest signal - someone aggressively buying fresh contracts
        if voi_ratio >= self.sweep_voi_threshold and total_premium >= 100_000:
            if option_type == 'call':
                return 'bullish_sweep'
            else:
                return 'bearish_sweep'

        # Volume surge: High V/OI with good premium
        if voi_ratio >= self.min_voi_ratio:
            if option_type == 'call' and otm_pct > 0:
                return 'call_surge'
            elif option_type == 'put' and otm_pct > 0:
                return 'put_surge'

        # Near-term heavy volume (event positioning) - lower V/OI threshold
        if dte <= 7 and voi_ratio >= 1.5 and total_premium >= 75_000:
            if option_type == 'call':
                return 'call_surge'
            elif option_type == 'put':
                return 'put_surge'

        return None

    def _detect_straddle_activity(
        self,
        symbol: str,
        calls: pd.DataFrame,
        puts: pd.DataFrame,
        stock_price: float,
        expiry: str,
        dte: int
    ) -> List[UnusualFlow]:
        """Detect unusual straddle/strangle activity (both sides heavy)"""
        flows = []

        if calls.empty or puts.empty:
            return flows

        try:
            # Find ATM strikes (within 2% of stock price)
            atm_calls = calls[
                (calls['strike'] >= stock_price * 0.98) &
                (calls['strike'] <= stock_price * 1.02)
            ]
            atm_puts = puts[
                (puts['strike'] >= stock_price * 0.98) &
                (puts['strike'] <= stock_price * 1.02)
            ]

            if atm_calls.empty or atm_puts.empty:
                return flows

            for _, call_row in atm_calls.iterrows():
                strike = call_row['strike']
                call_vol = int(call_row.get('volume', 0) or 0)
                call_price = float(call_row.get('lastPrice', 0) or 0)

                # Find matching put at same strike
                matching_puts = atm_puts[atm_puts['strike'] == strike]
                if matching_puts.empty:
                    continue

                put_row = matching_puts.iloc[0]
                put_vol = int(put_row.get('volume', 0) or 0)
                put_price = float(put_row.get('lastPrice', 0) or 0)

                # Both sides need meaningful volume
                if call_vol < 200 or put_vol < 200:
                    continue

                # Similar volume on both sides = straddle
                vol_ratio = min(call_vol, put_vol) / max(call_vol, put_vol)
                if vol_ratio < 0.4:  # Volume too skewed for straddle
                    continue

                total_vol = call_vol + put_vol
                total_premium = (call_vol * call_price + put_vol * put_price) * 100

                if total_premium < self.min_premium:
                    continue

                call_oi = int(call_row.get('openInterest', 0) or 0)
                put_oi = int(put_row.get('openInterest', 0) or 0)
                total_oi = max(call_oi + put_oi, 1)
                voi_ratio = total_vol / total_oi

                flow_key = f"{symbol}_{strike}_{expiry}_straddle"
                if flow_key in self.seen_flows:
                    continue

                flows.append(UnusualFlow(
                    symbol=symbol,
                    flow_type='straddle',
                    strike=strike,
                    expiry=expiry,
                    days_to_expiry=dte,
                    option_type='straddle',
                    volume=total_vol,
                    open_interest=total_oi,
                    voi_ratio=voi_ratio,
                    implied_premium=total_premium,
                    stock_price=stock_price,
                    otm_pct=0.0,
                    details={
                        'call_volume': call_vol,
                        'put_volume': put_vol,
                        'call_price': call_price,
                        'put_price': put_price,
                        'straddle_cost': (call_price + put_price) * 100,
                        'breakeven_up_pct': ((strike + call_price + put_price - stock_price) / stock_price) * 100,
                        'breakeven_down_pct': ((stock_price - (strike - call_price - put_price)) / stock_price) * 100,
                    }
                ))
                self.seen_flows.add(flow_key)

        except Exception as e:
            logger.debug(f"[OptionsFlow] Straddle detection error for {symbol}: {e}")

        return flows

    def _generate_signal(self, symbol: str, flows: List[UnusualFlow]) -> Optional[Signal]:
        """Generate a trading signal from unusual options flow"""
        if not flows:
            return None

        # Aggregate flow data
        total_premium = sum(f.implied_premium for f in flows)
        bullish_flows = [f for f in flows if f.flow_type in ('bullish_sweep', 'call_surge')]
        bearish_flows = [f for f in flows if f.flow_type in ('bearish_sweep', 'put_surge')]
        straddle_flows = [f for f in flows if f.flow_type == 'straddle']

        bullish_premium = sum(f.implied_premium for f in bullish_flows)
        bearish_premium = sum(f.implied_premium for f in bearish_flows)

        # Determine overall flow direction
        if straddle_flows and not bullish_flows and not bearish_flows:
            # Pure straddle - expect big move but unclear direction
            # Skip for now - we need directional signals
            return None

        if bullish_premium > bearish_premium * 2:
            direction = 'bullish'
            key_flows = bullish_flows
        elif bearish_premium > bullish_premium * 2:
            direction = 'bearish'
            key_flows = bearish_flows
        else:
            # Mixed flow - skip
            return None

        if not key_flows:
            return None

        # Use the strongest flow for signal parameters
        strongest = key_flows[0]
        stock_price = strongest.stock_price

        # Calculate confidence based on flow strength
        confidence = 0.58  # Base confidence for options flow

        # V/OI ratio bonus
        max_voi = max(f.voi_ratio for f in key_flows)
        if max_voi >= 10.0:
            confidence += 0.10  # Very unusual
        elif max_voi >= 5.0:
            confidence += 0.07  # Sweep-level
        elif max_voi >= 3.0:
            confidence += 0.04

        # Premium bonus
        directional_premium = bullish_premium if direction == 'bullish' else bearish_premium
        if directional_premium >= 500_000:
            confidence += 0.08  # Half million+ = serious money
        elif directional_premium >= 200_000:
            confidence += 0.05
        elif directional_premium >= 100_000:
            confidence += 0.03

        # Multiple flow signals bonus
        if len(key_flows) >= 3:
            confidence += 0.05
        elif len(key_flows) >= 2:
            confidence += 0.03

        # Sweep bonus (strongest signal type)
        has_sweep = any(f.flow_type in ('bullish_sweep', 'bearish_sweep') for f in key_flows)
        if has_sweep:
            confidence += 0.05

        # Near-term expiry bonus (event positioning)
        min_dte = min(f.days_to_expiry for f in key_flows)
        if min_dte <= 7:
            confidence += 0.03  # Someone paying for weeklies = urgency

        confidence = min(confidence, 0.90)

        # Build signal
        if direction == 'bullish':
            signal_type = SignalType.BUY
            # Target: average OTM target from flows
            avg_otm = np.mean([f.otm_pct for f in key_flows if f.otm_pct > 0]) if key_flows else 5.0
            target_pct = max(avg_otm, 3.0)  # At least 3% move
            target_price = stock_price * (1 + target_pct / 100)
            stop_loss = stock_price * 0.95  # 5% stop
        else:
            signal_type = SignalType.SELL
            avg_otm = np.mean([f.otm_pct for f in key_flows if f.otm_pct > 0]) if key_flows else 5.0
            target_pct = max(avg_otm, 3.0)
            target_price = stock_price * (1 - target_pct / 100)
            stop_loss = stock_price * 1.05  # 5% stop

        rr_ratio = abs(target_price - stock_price) / abs(stock_price - stop_loss) if abs(stock_price - stop_loss) > 0 else 0

        if rr_ratio < 1.5:
            return None

        # Build flow details for metadata
        flow_details = []
        for f in key_flows[:5]:
            flow_details.append(
                f"{f.flow_type}: {f.option_type.upper()} ${f.strike} "
                f"exp {f.expiry} | Vol: {f.volume:,} vs OI: {f.open_interest:,} "
                f"(V/OI: {f.voi_ratio:.1f}x) | Premium: ${f.implied_premium:,.0f}"
            )

        return Signal(
            symbol=symbol,
            market_type=MarketType.OPTIONS,
            signal_type=signal_type,
            confidence=confidence,
            entry_price=stock_price,
            target_price=target_price,
            stop_loss=stop_loss,
            risk_reward_ratio=rr_ratio,
            source="unusual_options_flow",
            metadata={
                'strategy': 'unusual_options_flow',
                'flow_direction': direction,
                'total_premium': total_premium,
                'directional_premium': directional_premium,
                'num_flows': len(key_flows),
                'has_sweep': has_sweep,
                'max_voi_ratio': max_voi,
                'min_dte': min_dte,
                'strongest_strike': strongest.strike,
                'strongest_expiry': strongest.expiry,
                'flow_details': flow_details,
                'stock_price': stock_price,
            }
        )

    def _cleanup_old_flows(self):
        """Remove flow data older than 3 days"""
        cutoff = datetime.now() - timedelta(days=3)
        expired_symbols = []
        for symbol, flows in self.recent_flows.items():
            # Keep only if we have recent data
            if not flows:
                expired_symbols.append(symbol)
        for s in expired_symbols:
            del self.recent_flows[s]

        # Clean seen flows periodically (reset every 24h to catch new activity)
        if self.last_scan and (datetime.now() - self.last_scan).total_seconds() > 86400:
            self.seen_flows.clear()

    async def _broadcast_signal(self, signal: Signal) -> None:
        """Send signal to coordinator"""
        await self.send_message(
            target='coordinator',
            msg_type='new_signal',
            payload={
                'symbol': signal.symbol,
                'market_type': signal.market_type.value,
                'signal_type': signal.signal_type.value,
                'confidence': signal.confidence,
                'entry_price': signal.entry_price,
                'target_price': signal.target_price,
                'stop_loss': signal.stop_loss,
                'risk_reward_ratio': signal.risk_reward_ratio,
                'source': signal.source,
                'timestamp': signal.timestamp.isoformat(),
                'metadata': signal.metadata
            },
            priority=2  # High priority - flow signals are time-sensitive
        )

    async def handle_message(self, message: AgentMessage) -> None:
        """Handle incoming messages"""
        if message.msg_type == 'update_watchlist':
            self.watchlist = message.payload.get('symbols', [])
            logger.info(f"[OptionsFlow] Watchlist updated: {len(self.watchlist)} symbols")

        elif message.msg_type == 'force_scan':
            self.last_scan = None

        elif message.msg_type == 'pause_scanning':
            await self.pause()

        elif message.msg_type == 'resume_scanning':
            await self.resume()

    def get_flow_summary(self, symbol: str) -> Optional[Dict]:
        """Get summary of recent unusual flow for a symbol"""
        flows = self.recent_flows.get(symbol)
        if not flows:
            return None

        return {
            'symbol': symbol,
            'num_flows': len(flows),
            'total_premium': sum(f.implied_premium for f in flows),
            'flow_types': [f.flow_type for f in flows],
            'max_voi': max(f.voi_ratio for f in flows),
            'strikes': [f.strike for f in flows],
        }

    def get_status(self) -> Dict[str, Any]:
        """Get scanner status"""
        return {
            'name': self.name,
            'state': self.state.value,
            'last_scan': self.last_scan.isoformat() if self.last_scan else None,
            'watchlist_size': len(self.watchlist),
            'active_flows': sum(len(f) for f in self.recent_flows.values()),
            'symbols_with_flow': list(self.recent_flows.keys()),
            'metrics': self.metrics
        }
