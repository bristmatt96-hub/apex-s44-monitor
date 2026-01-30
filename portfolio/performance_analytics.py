"""
Performance Analytics

Track win rate, expectancy, R-multiples, and other key metrics.
Know if your edge is actually working.

"What gets measured gets managed." - Peter Drucker
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
from loguru import logger

from portfolio.trade_journal import get_trade_journal, TradeEntry


@dataclass
class PerformanceMetrics:
    """Performance metrics for a period"""
    period: str
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float

    total_pnl: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float

    profit_factor: float  # Gross profit / Gross loss
    expectancy: float     # Expected value per trade
    expectancy_r: float   # Expected R per trade

    avg_r_multiple: float
    total_r: float

    avg_hold_time: str
    best_strategy: str
    worst_strategy: str


class PerformanceAnalytics:
    """
    Analyzes trading performance across multiple dimensions.

    Key metrics:
    - Win Rate: % of winning trades
    - Profit Factor: Gross profits / Gross losses (>1 is profitable)
    - Expectancy: Expected $ per trade
    - R-Multiple: How many R's (risk units) gained/lost
    - Sharpe-like: Risk-adjusted returns

    "It's not about being right, it's about how much you make when
    you're right vs how much you lose when you're wrong."
    """

    def __init__(self):
        self.journal = get_trade_journal()

    def get_metrics(self, days: Optional[int] = None) -> PerformanceMetrics:
        """Calculate performance metrics for a period"""
        trades = self.journal.get_closed_trades(days)

        if not trades:
            return PerformanceMetrics(
                period=f"Last {days} days" if days else "All time",
                total_trades=0,
                wins=0, losses=0, breakeven=0,
                win_rate=0.0,
                total_pnl=0.0,
                avg_win=0.0, avg_loss=0.0,
                largest_win=0.0, largest_loss=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                expectancy_r=0.0,
                avg_r_multiple=0.0,
                total_r=0.0,
                avg_hold_time="N/A",
                best_strategy="N/A",
                worst_strategy="N/A"
            )

        # Basic counts
        wins = [t for t in trades if t.outcome == 'win']
        losses = [t for t in trades if t.outcome == 'loss']
        breakeven = [t for t in trades if t.outcome == 'breakeven']

        win_rate = len(wins) / len(trades) * 100 if trades else 0

        # P&L metrics
        total_pnl = sum(t.pnl or 0 for t in trades)
        gross_profit = sum(t.pnl for t in wins if t.pnl)
        gross_loss = abs(sum(t.pnl for t in losses if t.pnl))

        avg_win = gross_profit / len(wins) if wins else 0
        avg_loss = gross_loss / len(losses) if losses else 0

        largest_win = max((t.pnl for t in wins if t.pnl), default=0)
        largest_loss = min((t.pnl for t in losses if t.pnl), default=0)

        # Profit factor
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Expectancy (expected value per trade)
        expectancy = total_pnl / len(trades) if trades else 0

        # R-Multiple analysis
        trades_with_r = [t for t in trades if t.r_multiple is not None]
        if trades_with_r:
            total_r = sum(t.r_multiple for t in trades_with_r)
            avg_r = total_r / len(trades_with_r)
            expectancy_r = total_r / len(trades)  # R per trade including those without R
        else:
            total_r = 0
            avg_r = 0
            expectancy_r = 0

        # Strategy analysis
        strategy_pnl = defaultdict(float)
        for t in trades:
            strategy_pnl[t.strategy or 'unknown'] += t.pnl or 0

        best_strategy = max(strategy_pnl.items(), key=lambda x: x[1])[0] if strategy_pnl else "N/A"
        worst_strategy = min(strategy_pnl.items(), key=lambda x: x[1])[0] if strategy_pnl else "N/A"

        # Average hold time (simplified)
        avg_hold_time = self._calculate_avg_hold_time(trades)

        return PerformanceMetrics(
            period=f"Last {days} days" if days else "All time",
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            breakeven=len(breakeven),
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            profit_factor=profit_factor,
            expectancy=expectancy,
            expectancy_r=expectancy_r,
            avg_r_multiple=avg_r,
            total_r=total_r,
            avg_hold_time=avg_hold_time,
            best_strategy=best_strategy,
            worst_strategy=worst_strategy
        )

    def _calculate_avg_hold_time(self, trades: List[TradeEntry]) -> str:
        """Calculate average hold time"""
        total_hours = 0
        count = 0

        for t in trades:
            if t.entry_date and t.exit_date:
                try:
                    entry = datetime.fromisoformat(t.entry_date)
                    exit = datetime.fromisoformat(t.exit_date)
                    hours = (exit - entry).total_seconds() / 3600
                    total_hours += hours
                    count += 1
                except:
                    pass

        if count == 0:
            return "N/A"

        avg_hours = total_hours / count

        if avg_hours < 1:
            return f"{int(avg_hours * 60)}m"
        elif avg_hours < 24:
            return f"{avg_hours:.1f}h"
        else:
            return f"{avg_hours / 24:.1f}d"

    def get_streak_info(self) -> Dict:
        """Get current winning/losing streak info"""
        trades = self.journal.get_closed_trades()

        if not trades:
            return {'current_streak': 0, 'streak_type': 'none', 'max_win_streak': 0, 'max_loss_streak': 0}

        # Sort by exit date
        sorted_trades = sorted(trades, key=lambda t: t.exit_date or '', reverse=True)

        # Current streak
        current_streak = 0
        streak_type = None

        for t in sorted_trades:
            if streak_type is None:
                streak_type = t.outcome
                current_streak = 1
            elif t.outcome == streak_type:
                current_streak += 1
            else:
                break

        # Historical max streaks
        max_win = 0
        max_loss = 0
        current_win = 0
        current_loss = 0

        for t in sorted(trades, key=lambda t: t.exit_date or ''):
            if t.outcome == 'win':
                current_win += 1
                current_loss = 0
                max_win = max(max_win, current_win)
            elif t.outcome == 'loss':
                current_loss += 1
                current_win = 0
                max_loss = max(max_loss, current_loss)
            else:
                current_win = 0
                current_loss = 0

        return {
            'current_streak': current_streak,
            'streak_type': streak_type,
            'max_win_streak': max_win,
            'max_loss_streak': max_loss
        }

    def get_drawdown_analysis(self) -> Dict:
        """Analyze drawdown from peak"""
        trades = self.journal.get_closed_trades()

        if not trades:
            return {'max_drawdown': 0, 'max_drawdown_pct': 0, 'current_drawdown': 0}

        # Sort by date
        sorted_trades = sorted(trades, key=lambda t: t.exit_date or '')

        cumulative = 0
        peak = 0
        max_dd = 0
        drawdowns = []

        for t in sorted_trades:
            cumulative += t.pnl or 0
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
            drawdowns.append(dd)

        current_dd = drawdowns[-1] if drawdowns else 0

        return {
            'max_drawdown': max_dd,
            'current_drawdown': current_dd,
            'peak_equity': peak
        }

    def get_time_analysis(self) -> Dict:
        """Analyze performance by time of day/week"""
        trades = self.journal.get_closed_trades()

        by_day = defaultdict(lambda: {'trades': 0, 'pnl': 0})
        by_hour = defaultdict(lambda: {'trades': 0, 'pnl': 0})

        for t in trades:
            if t.entry_date:
                try:
                    dt = datetime.fromisoformat(t.entry_date)
                    day = dt.strftime('%A')
                    hour = dt.hour

                    by_day[day]['trades'] += 1
                    by_day[day]['pnl'] += t.pnl or 0

                    by_hour[hour]['trades'] += 1
                    by_hour[hour]['pnl'] += t.pnl or 0
                except:
                    pass

        # Best/worst day
        best_day = max(by_day.items(), key=lambda x: x[1]['pnl'])[0] if by_day else "N/A"
        worst_day = min(by_day.items(), key=lambda x: x[1]['pnl'])[0] if by_day else "N/A"

        # Best/worst hour
        best_hour = max(by_hour.items(), key=lambda x: x[1]['pnl'])[0] if by_hour else "N/A"
        worst_hour = min(by_hour.items(), key=lambda x: x[1]['pnl'])[0] if by_hour else "N/A"

        return {
            'by_day': dict(by_day),
            'by_hour': dict(by_hour),
            'best_day': best_day,
            'worst_day': worst_day,
            'best_hour': best_hour,
            'worst_hour': worst_hour
        }

    def get_edge_assessment(self) -> Dict:
        """Assess if we have a statistical edge"""
        metrics = self.get_metrics()

        assessment = {
            'has_edge': False,
            'confidence': 'low',
            'issues': [],
            'strengths': []
        }

        if metrics.total_trades < 30:
            assessment['issues'].append("Need 30+ trades for statistical significance")
            return assessment

        # Win rate assessment
        if metrics.win_rate >= 50:
            assessment['strengths'].append(f"Solid win rate: {metrics.win_rate:.0f}%")
        else:
            if metrics.avg_win > metrics.avg_loss * 2:
                assessment['strengths'].append("Low win rate but winners are 2x+ losers")
            else:
                assessment['issues'].append(f"Low win rate ({metrics.win_rate:.0f}%) without size advantage")

        # Profit factor
        if metrics.profit_factor > 1.5:
            assessment['strengths'].append(f"Strong profit factor: {metrics.profit_factor:.2f}")
            assessment['has_edge'] = True
        elif metrics.profit_factor > 1.0:
            assessment['strengths'].append(f"Profitable (PF: {metrics.profit_factor:.2f})")
            assessment['has_edge'] = True
        else:
            assessment['issues'].append(f"Unprofitable - profit factor: {metrics.profit_factor:.2f}")

        # Expectancy
        if metrics.expectancy > 0:
            assessment['strengths'].append(f"Positive expectancy: ${metrics.expectancy:.2f}/trade")
        else:
            assessment['issues'].append(f"Negative expectancy: ${metrics.expectancy:.2f}/trade")

        # R-multiple
        if metrics.avg_r_multiple > 0.5:
            assessment['strengths'].append(f"Good R average: {metrics.avg_r_multiple:.2f}R")
        elif metrics.avg_r_multiple < 0:
            assessment['issues'].append(f"Negative R average: {metrics.avg_r_multiple:.2f}R")

        # Drawdown
        dd = self.get_drawdown_analysis()
        if dd['max_drawdown'] > metrics.total_pnl * 0.5:
            assessment['issues'].append("Large drawdowns relative to profits")

        # Set confidence
        if len(assessment['strengths']) >= 3 and len(assessment['issues']) <= 1:
            assessment['confidence'] = 'high'
        elif len(assessment['strengths']) >= 2:
            assessment['confidence'] = 'medium'

        return assessment

    def format_performance_report(self, days: int = 30) -> str:
        """Format comprehensive performance report"""
        lines = []
        lines.append("=" * 60)
        lines.append("           PERFORMANCE ANALYTICS")
        lines.append("=" * 60)

        metrics = self.get_metrics(days)
        all_time = self.get_metrics()

        # Summary
        lines.append(f"\n  Period: {metrics.period}")
        lines.append(f"  Total Trades: {metrics.total_trades}")

        if metrics.total_trades == 0:
            lines.append("\n  No closed trades to analyze")
            return "\n".join(lines)

        # Win/Loss
        lines.append(f"\n  WIN/LOSS RECORD:")
        lines.append(f"    Wins: {metrics.wins} | Losses: {metrics.losses} | BE: {metrics.breakeven}")
        lines.append(f"    Win Rate: {metrics.win_rate:.1f}%")

        # P&L
        lines.append(f"\n  P&L METRICS:")
        lines.append(f"    Total P&L: ${metrics.total_pnl:+,.2f}")
        lines.append(f"    Avg Win: ${metrics.avg_win:,.2f}")
        lines.append(f"    Avg Loss: ${metrics.avg_loss:,.2f}")
        lines.append(f"    Largest Win: ${metrics.largest_win:+,.2f}")
        lines.append(f"    Largest Loss: ${metrics.largest_loss:+,.2f}")

        # Key metrics
        lines.append(f"\n  KEY METRICS:")
        pf_str = f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float('inf') else "∞"
        lines.append(f"    Profit Factor: {pf_str}")
        lines.append(f"    Expectancy: ${metrics.expectancy:+.2f}/trade")
        lines.append(f"    Avg R-Multiple: {metrics.avg_r_multiple:+.2f}R")
        lines.append(f"    Total R: {metrics.total_r:+.1f}R")

        # Streaks
        streak = self.get_streak_info()
        streak_emoji = "🔥" if streak['streak_type'] == 'win' else "❄️" if streak['streak_type'] == 'loss' else ""
        lines.append(f"\n  STREAKS:")
        lines.append(f"    Current: {streak['current_streak']} {streak['streak_type']} {streak_emoji}")
        lines.append(f"    Max Win Streak: {streak['max_win_streak']}")
        lines.append(f"    Max Loss Streak: {streak['max_loss_streak']}")

        # Drawdown
        dd = self.get_drawdown_analysis()
        lines.append(f"\n  DRAWDOWN:")
        lines.append(f"    Max Drawdown: ${dd['max_drawdown']:,.2f}")
        lines.append(f"    Current DD: ${dd['current_drawdown']:,.2f}")

        # Strategy performance
        lines.append(f"\n  STRATEGY PERFORMANCE:")
        lines.append(f"    Best: {metrics.best_strategy}")
        lines.append(f"    Worst: {metrics.worst_strategy}")

        # Edge assessment
        edge = self.get_edge_assessment()
        lines.append(f"\n  EDGE ASSESSMENT:")
        edge_emoji = "✅" if edge['has_edge'] else "❌"
        lines.append(f"    Has Edge: {edge_emoji} (Confidence: {edge['confidence']})")

        if edge['strengths']:
            lines.append("    Strengths:")
            for s in edge['strengths'][:3]:
                lines.append(f"      ✓ {s}")

        if edge['issues']:
            lines.append("    Issues:")
            for i in edge['issues'][:3]:
                lines.append(f"      ⚠ {i}")

        # All-time comparison
        if days and all_time.total_trades > metrics.total_trades:
            lines.append(f"\n  ALL-TIME ({all_time.total_trades} trades):")
            lines.append(f"    Win Rate: {all_time.win_rate:.1f}%")
            lines.append(f"    Total P&L: ${all_time.total_pnl:+,.2f}")

        lines.append("")
        return "\n".join(lines)


# Singleton
_analytics_instance: Optional[PerformanceAnalytics] = None

def get_performance_analytics() -> PerformanceAnalytics:
    """Get or create performance analytics instance"""
    global _analytics_instance
    if _analytics_instance is None:
        _analytics_instance = PerformanceAnalytics()
    return _analytics_instance


if __name__ == "__main__":
    analytics = get_performance_analytics()
    print(analytics.format_performance_report())
