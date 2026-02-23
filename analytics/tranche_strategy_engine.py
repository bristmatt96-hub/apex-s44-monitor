#!/usr/bin/env python3
"""
Tranche Strategy Engine
========================
Trade construction, delta hedging, position management, and P&L attribution
for iTraxx Main and Crossover equity tranche dispersion strategies.

Capabilities:
  - Construct dispersion trades (long/short equity tranche + index hedge)
  - Compute delta hedge ratios and rebalancing needs
  - P&L attribution (carry + spread + correlation + theta + default)
  - Generate trade signals based on dispersion monitor output
  - Stress test under 8 macro/tranche scenarios
  - Track active positions and cumulative P&L

Data Sources:
  - cds_tranche_pricer (tranche pricing, Greeks)
  - dispersion_correlation_monitor (dispersion signals)
  - scenario_analysis_engine (macro scenarios)

Usage:
  python tranche_strategy_engine.py

Author: Built with Claude for macro credit trading
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

warnings.filterwarnings("ignore")

PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_AUM = 100_000_000  # $100mm
MAX_ALLOCATION_PCT = 0.30   # Max 30% of AUM in any single strategy
EQUITY_TRANCHE_RUNNING = 500  # bps standard running on equity tranche

# Stress scenario definitions (5 macro + 3 tranche-specific)
SCENARIOS = {
    "HARD_LANDING": {
        "label": "Hard Landing", "color": "#e74c3c",
        "spread_chg_bps": +350, "corr_chg": +0.20, "defaults": 3, "vix_target": 45,
        "description": "Recession, defaults spike, spread blowout",
    },
    "SOFT_LANDING": {
        "label": "Soft Landing", "color": "#2ecc71",
        "spread_chg_bps": -30, "corr_chg": -0.05, "defaults": 0, "vix_target": 15,
        "description": "Goldilocks: carry dominates, spreads tighten",
    },
    "NO_LANDING": {
        "label": "No Landing", "color": "#f39c12",
        "spread_chg_bps": +30, "corr_chg": 0.0, "defaults": 0, "vix_target": 18,
        "description": "Growth reaccelerates, rates higher for longer",
    },
    "STAGFLATION": {
        "label": "Stagflation", "color": "#9b59b6",
        "spread_chg_bps": +250, "corr_chg": +0.15, "defaults": 2, "vix_target": 32,
        "description": "Growth stalls, inflation sticky, no policy put",
    },
    "CREDIT_CRISIS": {
        "label": "Credit Crisis", "color": "#1a1a2e",
        "spread_chg_bps": +600, "corr_chg": +0.35, "defaults": 5, "vix_target": 65,
        "description": "Systemic event, forced selling, correlation 1",
    },
    "CORRELATION_SPIKE": {
        "label": "Correlation Spike", "color": "#c0392b",
        "spread_chg_bps": +100, "corr_chg": +0.40, "defaults": 1, "vix_target": 35,
        "description": "Correlation jumps to 80%, equity tranche loses",
    },
    "MULTI_DEFAULT": {
        "label": "Multi Default", "color": "#2c3e50",
        "spread_chg_bps": +150, "corr_chg": +0.10, "defaults": 3, "vix_target": 38,
        "description": "3 worst names default simultaneously",
    },
    "SPREAD_GAMMA": {
        "label": "Spread Gamma", "color": "#e67e22",
        "spread_chg_bps": +200, "corr_chg": +0.05, "defaults": 0, "vix_target": 28,
        "description": "+200bp parallel shift, test convexity",
    },
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TranchePosition:
    """A tranche position with pricing and Greeks."""
    position_id: str
    index_name: str           # "Main" or "Crossover"
    tranche_label: str        # e.g. "0-3%"
    attach: float
    detach: float
    notional_mm: float        # tranche notional in $mm
    is_long_protection: bool  # True = bought protection (pay spread)
    entry_date: str
    entry_upfront_pct: float
    entry_running_bps: float
    entry_base_corr: float
    entry_fair_spread: float
    current_fair_spread: float
    current_base_corr: float
    cs01_per_mm: float        # from Greeks
    rho01_per_mm: float
    delta_ratio: float
    theta_daily_per_mm: float
    expected_loss_pct: float


@dataclass
class IndexHedge:
    """Index hedge position (delta hedge for tranche)."""
    index_name: str           # "Main" or "Crossover"
    notional_mm: float        # index notional
    is_long_protection: bool  # opposite of tranche for delta-neutral
    entry_spread_bps: float
    current_spread_bps: float
    duration: float


@dataclass
class DispersionTrade:
    """Complete dispersion trade: tranche + index hedge."""
    trade_id: str
    strategy: str             # "LONG_DISPERSION" or "SHORT_DISPERSION"
    tranche_leg: TranchePosition
    index_hedge: IndexHedge
    entry_date: str
    days_held: int
    # Net Greeks
    net_cs01: float           # net spread sensitivity
    net_rho01: float          # correlation sensitivity
    net_theta_daily: float
    # P&L components (in $)
    pnl_carry: float
    pnl_spread: float
    pnl_correlation: float
    pnl_theta: float
    pnl_default: float
    pnl_total: float
    # Status
    status: str               # "ACTIVE" / "CLOSED"


@dataclass
class TradeSignal:
    """Signal to enter/exit a trade."""
    action: str               # ENTER_LONG_DISP / ENTER_SHORT_DISP / EXIT / HOLD
    confidence: str           # LOW / MEDIUM / HIGH
    sizing_pct: float         # % of AUM
    notional_mm: float        # recommended notional
    rationale: str
    dispersion_score: float   # from dispersion monitor
    macro_regime: str


@dataclass
class StressResult:
    """P&L under a stress scenario."""
    scenario_name: str
    scenario_description: str
    tranche_pnl: float
    index_hedge_pnl: float
    net_pnl: float
    net_pnl_pct_aum: float
    spread_component: float
    corr_component: float
    default_component: float


# =============================================================================
# TRADE CONSTRUCTION
# =============================================================================

def compute_delta_hedge_ratio(tranche_cs01: float, index_duration: float = 4.5) -> float:
    """
    Compute the index notional needed to delta-hedge a tranche.
    Delta ratio = tranche CS01 / index CS01 per unit notional.
    Index CS01 ~ duration / 10000 * notional_mm.

    Returns: index_notional / tranche_notional ratio.
    """
    index_cs01_per_mm = index_duration / 10000 * 1e6  # $ per 1bp per $1mm
    if index_cs01_per_mm <= 0:
        return 1.0
    return tranche_cs01 / index_cs01_per_mm


def construct_dispersion_trade(
    strategy: str,
    index_name: str,
    tranche_notional_mm: float,
    tranche_label: str,
    tranche_attach: float,
    tranche_detach: float,
    tranche_fair_spread: float,
    tranche_upfront_pct: float,
    tranche_running_bps: float,
    tranche_base_corr: float,
    tranche_el_pct: float,
    tranche_cs01: float,
    tranche_rho01: float,
    tranche_delta_ratio: float,
    tranche_theta: float,
    index_spread_bps: float,
    index_duration: float = 4.5,
    trade_id: str = None,
) -> DispersionTrade:
    """
    Construct a complete dispersion trade with delta hedge.

    strategy: "LONG_DISPERSION" or "SHORT_DISPERSION"
    LONG DISPERSION: buy equity tranche protection + sell delta-hedged index protection
    SHORT DISPERSION: sell equity tranche protection + buy delta-hedged index protection
    """
    if trade_id is None:
        trade_id = f"DISP_{index_name[:4]}_{datetime.now().strftime('%Y%m%d_%H%M')}"

    is_long_prot_tranche = (strategy == "LONG_DISPERSION")
    is_long_prot_index = not is_long_prot_tranche  # opposite for delta-neutral

    # Index hedge notional
    hedge_ratio = compute_delta_hedge_ratio(tranche_cs01, index_duration)
    index_notional_mm = tranche_notional_mm * hedge_ratio

    # Build tranche leg
    tranche_leg = TranchePosition(
        position_id=f"{trade_id}_TRANCHE",
        index_name=index_name,
        tranche_label=tranche_label,
        attach=tranche_attach,
        detach=tranche_detach,
        notional_mm=tranche_notional_mm,
        is_long_protection=is_long_prot_tranche,
        entry_date=datetime.now().strftime("%Y-%m-%d"),
        entry_upfront_pct=tranche_upfront_pct,
        entry_running_bps=tranche_running_bps,
        entry_base_corr=tranche_base_corr,
        entry_fair_spread=tranche_fair_spread,
        current_fair_spread=tranche_fair_spread,
        current_base_corr=tranche_base_corr,
        cs01_per_mm=tranche_cs01,
        rho01_per_mm=tranche_rho01,
        delta_ratio=tranche_delta_ratio,
        theta_daily_per_mm=tranche_theta,
        expected_loss_pct=tranche_el_pct,
    )

    # Build index hedge
    index_hedge = IndexHedge(
        index_name=index_name,
        notional_mm=index_notional_mm,
        is_long_protection=is_long_prot_index,
        entry_spread_bps=index_spread_bps,
        current_spread_bps=index_spread_bps,
        duration=index_duration,
    )

    # Net Greeks
    # Tranche direction multiplier
    t_dir = -1.0 if is_long_prot_tranche else 1.0
    h_dir = -1.0 if is_long_prot_index else 1.0

    # CS01: tranche CS01 is offset by index CS01 (delta neutral)
    tranche_total_cs01 = t_dir * tranche_cs01 * tranche_notional_mm / 1e6
    index_cs01_per_mm = index_duration / 10000 * 1e6
    index_total_cs01 = h_dir * index_cs01_per_mm * index_notional_mm / 1e6
    net_cs01 = tranche_total_cs01 + index_total_cs01

    # Rho01: only tranche has correlation sensitivity
    net_rho01 = t_dir * tranche_rho01 * tranche_notional_mm / 1e6

    # Theta: tranche theta (carry cost)
    net_theta = t_dir * tranche_theta * tranche_notional_mm / 1e6

    return DispersionTrade(
        trade_id=trade_id,
        strategy=strategy,
        tranche_leg=tranche_leg,
        index_hedge=index_hedge,
        entry_date=datetime.now().strftime("%Y-%m-%d"),
        days_held=0,
        net_cs01=round(net_cs01, 2),
        net_rho01=round(net_rho01, 2),
        net_theta_daily=round(net_theta, 2),
        pnl_carry=0,
        pnl_spread=0,
        pnl_correlation=0,
        pnl_theta=0,
        pnl_default=0,
        pnl_total=0,
        status="ACTIVE",
    )


# =============================================================================
# P&L ATTRIBUTION
# =============================================================================

def compute_trade_pnl(trade: DispersionTrade,
                       new_index_spread: float,
                       new_tranche_spread: float,
                       new_base_corr: float,
                       days: int = 1,
                       n_defaults: int = 0,
                       default_loss_per_name_pct: float = 0.6) -> Dict:
    """
    Compute P&L decomposition for a dispersion trade.

    Returns dict with carry, spread, correlation, theta, default components.
    """
    tl = trade.tranche_leg
    ih = trade.index_hedge

    t_dir = -1.0 if tl.is_long_protection else 1.0
    h_dir = -1.0 if ih.is_long_protection else 1.0

    # 1. CARRY (running spread received/paid)
    # Tranche: running spread * notional / 10000 * (days/360)
    tranche_carry = t_dir * tl.entry_running_bps / 10000 * tl.notional_mm * 1e6 * (days / 360)
    # Index: spread * notional / 10000 * (days/360)
    index_carry = h_dir * ih.entry_spread_bps / 10000 * ih.notional_mm * 1e6 * (days / 360)
    total_carry = tranche_carry + index_carry

    # 2. SPREAD P&L (mark-to-market from spread changes)
    spread_chg_tranche = new_tranche_spread - tl.current_fair_spread
    tranche_spread_pnl = t_dir * spread_chg_tranche * tl.cs01_per_mm * tl.notional_mm / 1e6

    spread_chg_index = new_index_spread - ih.current_spread_bps
    index_cs01_per_mm = ih.duration / 10000 * 1e6
    index_spread_pnl = h_dir * spread_chg_index * index_cs01_per_mm * ih.notional_mm / 1e6

    total_spread = tranche_spread_pnl + index_spread_pnl

    # 3. CORRELATION P&L (tranche only)
    corr_chg = new_base_corr - tl.current_base_corr
    corr_pnl = t_dir * corr_chg * 100 * tl.rho01_per_mm * tl.notional_mm / 1e6

    # 4. THETA (time decay)
    theta_pnl = t_dir * tl.theta_daily_per_mm * tl.notional_mm / 1e6 * days

    # 5. DEFAULT P&L (if any names default)
    default_pnl = 0
    if n_defaults > 0:
        # Equity tranche absorbs first losses
        tranche_width = tl.detach - tl.attach
        if tranche_width > 0:
            # Each default hits ~ 1/N * LGD of portfolio
            # For equity tranche: loss = min(cum_default_loss, detach) - attach
            n_names = 125 if tl.index_name == "Main" else 75
            per_default_loss = default_loss_per_name_pct / n_names
            cum_loss = per_default_loss * n_defaults

            tranche_loss = max(0, min(cum_loss, tl.detach) - tl.attach)
            tranche_loss_pct = tranche_loss / tranche_width
            # Long protection benefits, short protection loses
            default_pnl = -t_dir * tranche_loss_pct * tl.notional_mm * 1e6

            # Index hedge: defaults reduce index value
            index_loss_pct = per_default_loss * n_defaults
            index_default_pnl = -h_dir * index_loss_pct * ih.notional_mm * 1e6
            default_pnl += index_default_pnl

    total_pnl = total_carry + total_spread + corr_pnl + theta_pnl + default_pnl

    return {
        "carry": round(total_carry, 2),
        "spread": round(total_spread, 2),
        "correlation": round(corr_pnl, 2),
        "theta": round(theta_pnl, 2),
        "default": round(default_pnl, 2),
        "total": round(total_pnl, 2),
        "tranche_spread_pnl": round(tranche_spread_pnl, 2),
        "index_spread_pnl": round(index_spread_pnl, 2),
    }


# =============================================================================
# TRADE SIGNAL GENERATION
# =============================================================================

def generate_trade_signals(dispersion_score: float,
                            macro_regime: str,
                            existing_trades: List[DispersionTrade],
                            aum: float = DEFAULT_AUM,
                            index_name: str = "Crossover") -> List[TradeSignal]:
    """
    Generate trade signals based on dispersion signal and macro regime.
    """
    signals = []
    n_active = len([t for t in existing_trades if t.status == "ACTIVE"])

    # Check for exit signals on existing trades
    for trade in existing_trades:
        if trade.status != "ACTIVE":
            continue

        # Exit if signal has flipped
        if trade.strategy == "LONG_DISPERSION" and dispersion_score > 0.3:
            signals.append(TradeSignal(
                action="EXIT",
                confidence="MEDIUM",
                sizing_pct=0,
                notional_mm=trade.tranche_leg.notional_mm,
                rationale=f"Signal flipped positive ({dispersion_score:+.2f}), exit long dispersion",
                dispersion_score=dispersion_score,
                macro_regime=macro_regime,
            ))
        elif trade.strategy == "SHORT_DISPERSION" and dispersion_score < -0.3:
            signals.append(TradeSignal(
                action="EXIT",
                confidence="MEDIUM",
                sizing_pct=0,
                notional_mm=trade.tranche_leg.notional_mm,
                rationale=f"Signal flipped negative ({dispersion_score:+.2f}), exit short dispersion",
                dispersion_score=dispersion_score,
                macro_regime=macro_regime,
            ))

    # New trade signals
    if n_active >= 3:
        # Don't add more than 3 concurrent trades
        signals.append(TradeSignal(
            action="HOLD",
            confidence="N/A",
            sizing_pct=0,
            notional_mm=0,
            rationale=f"Max concurrent trades ({n_active}) reached, holding",
            dispersion_score=dispersion_score,
            macro_regime=macro_regime,
        ))
        return signals

    # Sizing based on signal strength and regime
    if abs(dispersion_score) < 0.15:
        # No edge
        signals.append(TradeSignal(
            action="HOLD",
            confidence="LOW",
            sizing_pct=0,
            notional_mm=0,
            rationale=f"Signal near zero ({dispersion_score:+.2f}), no trade",
            dispersion_score=dispersion_score,
            macro_regime=macro_regime,
        ))
        return signals

    # Determine direction and sizing
    if dispersion_score < -0.15:
        action = "ENTER_LONG_DISP"
        # Scale sizing: -0.15 to -2.0 -> 5% to 25% of AUM
        raw_pct = min(0.25, 0.05 + abs(dispersion_score) * 0.10)
    else:
        action = "ENTER_SHORT_DISP"
        raw_pct = min(0.25, 0.05 + abs(dispersion_score) * 0.10)

    # Regime adjustment
    regime_factor = 1.0
    if macro_regime in ("CRISIS", "HIGH_CORR"):
        if action == "ENTER_LONG_DISP":
            regime_factor = 0.5   # reduce long dispersion in crisis
        else:
            regime_factor = 1.2   # lean into short dispersion in crisis
    elif macro_regime in ("LOW_CORR",):
        if action == "ENTER_LONG_DISP":
            regime_factor = 1.2   # lean into long disp in low-corr
        else:
            regime_factor = 0.7

    sizing_pct = min(MAX_ALLOCATION_PCT, raw_pct * regime_factor)
    notional_mm = aum / 1e6 * sizing_pct

    # Confidence
    if abs(dispersion_score) >= 1.0:
        confidence = "HIGH"
    elif abs(dispersion_score) >= 0.5:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    strategy_name = "long" if "LONG" in action else "short"
    signals.append(TradeSignal(
        action=action,
        confidence=confidence,
        sizing_pct=round(sizing_pct * 100, 1),
        notional_mm=round(notional_mm, 2),
        rationale=f"Dispersion={dispersion_score:+.2f}, regime={macro_regime}, "
                  f"size={sizing_pct*100:.1f}% AUM ({strategy_name} disp)",
        dispersion_score=dispersion_score,
        macro_regime=macro_regime,
    ))

    return signals


# =============================================================================
# STRESS TESTING
# =============================================================================

def stress_test_trade(trade: DispersionTrade,
                       scenarios: Dict = None) -> List[StressResult]:
    """
    Stress test a dispersion trade under 8 scenarios.
    """
    if scenarios is None:
        scenarios = SCENARIOS

    results = []
    tl = trade.tranche_leg
    ih = trade.index_hedge

    for name, s in scenarios.items():
        spread_chg = s["spread_chg_bps"]
        corr_chg = s["corr_chg"]
        n_defaults = s["defaults"]

        # New spread levels
        new_index_spread = ih.current_spread_bps + spread_chg
        # Tranche spread changes more (leverage)
        new_tranche_spread = tl.current_fair_spread + spread_chg * tl.delta_ratio

        # New correlation
        new_corr = min(0.99, max(0.05, tl.current_base_corr + corr_chg))

        # Compute P&L
        pnl = compute_trade_pnl(
            trade, new_index_spread, new_tranche_spread, new_corr,
            days=30, n_defaults=n_defaults,
        )

        results.append(StressResult(
            scenario_name=s["label"],
            scenario_description=s["description"],
            tranche_pnl=pnl["tranche_spread_pnl"] + pnl["correlation"],
            index_hedge_pnl=pnl["index_spread_pnl"],
            net_pnl=pnl["total"],
            net_pnl_pct_aum=pnl["total"] / DEFAULT_AUM * 100 if DEFAULT_AUM > 0 else 0,
            spread_component=pnl["spread"],
            corr_component=pnl["correlation"],
            default_component=pnl["default"],
        ))

    return results


# =============================================================================
# CARRY ANALYSIS
# =============================================================================

def compute_carry_analysis(trade: DispersionTrade, periods: List[int] = None) -> Dict:
    """
    Compute carry (income) for a dispersion trade over different holding periods.
    """
    if periods is None:
        periods = [30, 90, 180, 365]

    tl = trade.tranche_leg
    ih = trade.index_hedge
    t_dir = -1.0 if tl.is_long_protection else 1.0
    h_dir = -1.0 if ih.is_long_protection else 1.0

    results = {}
    for days in periods:
        tranche_carry = t_dir * tl.entry_running_bps / 10000 * tl.notional_mm * 1e6 * (days / 360)
        index_carry = h_dir * ih.entry_spread_bps / 10000 * ih.notional_mm * 1e6 * (days / 360)
        total = tranche_carry + index_carry
        results[f"{days}d"] = {
            "tranche_carry": round(tranche_carry, 0),
            "index_carry": round(index_carry, 0),
            "net_carry": round(total, 0),
            "annualized_bps": round(total / (tl.notional_mm * 1e6) * 10000 * 360 / days, 1),
        }

    return results


# =============================================================================
# SYNTHETIC TRADE FOR STANDALONE TESTING
# =============================================================================

def create_sample_trade(strategy: str = "LONG_DISPERSION",
                         index_name: str = "Crossover",
                         aum: float = DEFAULT_AUM) -> DispersionTrade:
    """Create a sample dispersion trade for demonstration."""
    alloc_pct = 0.15  # 15% of AUM
    tranche_notional = aum / 1e6 * alloc_pct

    if index_name == "Main":
        label, attach, detach = "0-3%", 0.00, 0.03
        spread, upfront, running = 1300, 35.0, 500
        corr, el, cs01, rho01, delta, theta = 0.22, 58.0, 5500, -8750, 12.2, -30
        idx_spread = 55
    else:
        label, attach, detach = "0-10%", 0.00, 0.10
        spread, upfront, running = 2800, 45.0, 500
        corr, el, cs01, rho01, delta, theta = 0.28, 73.0, 4200, -6500, 9.5, -25
        idx_spread = 300

    return construct_dispersion_trade(
        strategy=strategy,
        index_name=index_name,
        tranche_notional_mm=tranche_notional,
        tranche_label=label,
        tranche_attach=attach,
        tranche_detach=detach,
        tranche_fair_spread=spread,
        tranche_upfront_pct=upfront,
        tranche_running_bps=running,
        tranche_base_corr=corr,
        tranche_el_pct=el,
        tranche_cs01=cs01,
        tranche_rho01=rho01,
        tranche_delta_ratio=delta,
        tranche_theta=theta,
        index_spread_bps=idx_spread,
        index_duration=4.5,
    )


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(trades: List[DispersionTrade],
                  signals: List[TradeSignal],
                  stress_results: Dict[str, List[StressResult]],
                  carry_analysis: Dict[str, Dict],
                  aum: float = DEFAULT_AUM):
    """Print formatted strategy engine report."""
    print("\n" + "=" * 110)
    print("  TRANCHE STRATEGY ENGINE")
    print("=" * 110)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  AUM: ${aum/1e6:.0f}mm")

    # 1. Active trades
    print(f"\n{'=' * 110}")
    print("  1. ACTIVE TRADES")
    print(f"{'=' * 110}")
    active = [t for t in trades if t.status == "ACTIVE"]
    if active:
        print(f"  {'Trade ID':<28s} {'Strategy':<18s} {'Index':<10s} {'Tranche':<8s} "
              f"{'Notional':>10s} {'Delta':>7s} {'Net CS01':>9s} {'Net Rho01':>10s}")
        print("  " + "-" * 105)
        for t in active:
            tl = t.tranche_leg
            print(f"  {t.trade_id:<28s} {t.strategy:<18s} {tl.index_name:<10s} "
                  f"{tl.tranche_label:<8s} ${tl.notional_mm:>8.1f}mm {tl.delta_ratio:>6.1f}x "
                  f"{t.net_cs01:>+8.0f} {t.net_rho01:>+9.0f}")
    else:
        print("  No active trades")

    # 2. Delta hedge summary
    print(f"\n{'=' * 110}")
    print("  2. DELTA HEDGE SUMMARY")
    print(f"{'=' * 110}")
    for t in active:
        tl = t.tranche_leg
        ih = t.index_hedge
        dir_t = "Long prot" if tl.is_long_protection else "Short prot"
        dir_h = "Long prot" if ih.is_long_protection else "Short prot"
        print(f"  Trade: {t.trade_id}")
        print(f"    Tranche: {tl.tranche_label} ({dir_t}) ${tl.notional_mm:.1f}mm | "
              f"CS01/mm=${tl.cs01_per_mm:.0f}, Delta={tl.delta_ratio:.1f}x")
        print(f"    Index:   {ih.index_name} ({dir_h}) ${ih.notional_mm:.1f}mm | "
              f"Spread={ih.current_spread_bps:.0f}bps, Duration={ih.duration:.1f}Y")
        print(f"    Hedge ratio: {ih.notional_mm / tl.notional_mm:.1f}x tranche notional")
        print(f"    Net CS01: {t.net_cs01:+.0f}$ (residual after delta hedge)")
        print()

    # 3. Trade signals
    print(f"\n{'=' * 110}")
    print("  3. TRADE SIGNALS")
    print(f"{'=' * 110}")
    for s in signals:
        color = "[!]" if s.confidence == "HIGH" else "[ ]" if s.confidence == "MEDIUM" else "   "
        print(f"  {color} {s.action:<22s} | Confidence: {s.confidence:<6s} | "
              f"Size: {s.sizing_pct:.1f}% (${s.notional_mm:.1f}mm)")
        print(f"       Rationale: {s.rationale}")
        print()

    # 4. Stress test results
    print(f"\n{'=' * 110}")
    print("  4. STRESS TEST (8 SCENARIOS)")
    print(f"{'=' * 110}")
    for trade_id, results in stress_results.items():
        print(f"\n  Trade: {trade_id}")
        print(f"  {'Scenario':<20s} {'Net P&L':>12s} {'% AUM':>8s} {'Spread':>10s} "
              f"{'Corr':>10s} {'Default':>10s}")
        print("  " + "-" * 80)
        for r in results:
            pnl_str = f"${r.net_pnl/1e6:+.2f}mm" if abs(r.net_pnl) > 1e6 else f"${r.net_pnl:+,.0f}"
            print(f"  {r.scenario_name:<20s} {pnl_str:>12s} {r.net_pnl_pct_aum:>+7.2f}% "
                  f"${r.spread_component:>+9,.0f} ${r.corr_component:>+9,.0f} "
                  f"${r.default_component:>+9,.0f}")

    # 5. Carry analysis
    print(f"\n{'=' * 110}")
    print("  5. CARRY ANALYSIS")
    print(f"{'=' * 110}")
    for trade_id, carry in carry_analysis.items():
        print(f"\n  Trade: {trade_id}")
        print(f"  {'Period':<8s} {'Tranche Carry':>14s} {'Index Carry':>13s} "
              f"{'Net Carry':>12s} {'Ann. bps':>10s}")
        print("  " + "-" * 60)
        for period, c in carry.items():
            print(f"  {period:<8s} ${c['tranche_carry']:>12,.0f} ${c['index_carry']:>11,.0f} "
                  f"${c['net_carry']:>10,.0f} {c['annualized_bps']:>9.1f}")

    # 6. JTD exposure
    print(f"\n{'=' * 110}")
    print("  6. KEY METRICS SUMMARY")
    print(f"{'=' * 110}")
    total_tranche_notional = sum(t.tranche_leg.notional_mm for t in active)
    total_index_notional = sum(t.index_hedge.notional_mm for t in active)
    total_net_cs01 = sum(t.net_cs01 for t in active)
    total_net_rho01 = sum(t.net_rho01 for t in active)
    total_theta = sum(t.net_theta_daily for t in active)

    print(f"  Total tranche notional:  ${total_tranche_notional:.1f}mm")
    print(f"  Total index notional:    ${total_index_notional:.1f}mm")
    print(f"  Gross leverage:          {(total_tranche_notional + total_index_notional) / (aum/1e6):.1f}x AUM")
    print(f"  Net CS01 (all trades):   ${total_net_cs01:+,.0f}")
    print(f"  Net Rho01 (all trades):  ${total_net_rho01:+,.0f}")
    print(f"  Net Theta/day:           ${total_theta:+,.0f}")

    print("\n" + "=" * 110)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(trades: List[DispersionTrade],
                    signals: List[TradeSignal],
                    stress_results: Dict[str, List[StressResult]],
                    carry_analysis: Dict[str, Dict],
                    aum: float = DEFAULT_AUM):
    """Create tranche strategy dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "TRANCHE STRATEGY ENGINE",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(0.5, 0.955,
             f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | AUM: ${aum/1e6:.0f}mm",
             ha="center", fontsize=10, color="gray")

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    active = [t for t in trades if t.status == "ACTIVE"]

    # --- Panel 1: P&L Waterfall ---
    ax1 = fig.add_subplot(gs[0, 0])
    if active:
        t = active[0]
        # Simulate P&L components for current trade
        components = ["Carry", "Spread", "Correlation", "Theta", "Default", "TOTAL"]
        values = [t.pnl_carry, t.pnl_spread, t.pnl_correlation, t.pnl_theta, t.pnl_default, t.pnl_total]
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in values]
        colors[-1] = "#3498db"  # total in blue

        bars = ax1.bar(range(len(components)), values, color=colors, edgecolor="white")
        ax1.set_xticks(range(len(components)))
        ax1.set_xticklabels(components, fontsize=7, rotation=30)
        ax1.axhline(0, color="black", linewidth=0.8)
        ax1.set_ylabel("P&L ($)")
    ax1.set_title("P&L Waterfall", fontweight="bold", fontsize=10)
    ax1.grid(True, alpha=0.3, axis="y")

    # --- Panel 2: Signal Dashboard Box ---
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.axis("off")

    if signals:
        s = signals[0]
        if "LONG" in s.action:
            box_color = "#e74c3c"
            label = "LONG DISPERSION"
        elif "SHORT" in s.action:
            box_color = "#2ecc71"
            label = "SHORT DISPERSION"
        else:
            box_color = "#f39c12"
            label = s.action

        box = FancyBboxPatch(
            (0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.03",
            facecolor=box_color, alpha=0.15, edgecolor=box_color, linewidth=3,
            transform=ax2.transAxes,
        )
        ax2.add_patch(box)
        ax2.text(0.5, 0.90, "TRADE SIGNAL", transform=ax2.transAxes,
                 ha="center", fontsize=11, fontweight="bold")
        ax2.text(0.5, 0.76, label, transform=ax2.transAxes,
                 ha="center", fontsize=14, fontweight="bold", color=box_color)
        ax2.text(0.5, 0.64, f"Dispersion: {s.dispersion_score:+.2f}", transform=ax2.transAxes,
                 ha="center", fontsize=10)
        ax2.text(0.5, 0.54, f"Confidence: {s.confidence}", transform=ax2.transAxes,
                 ha="center", fontsize=10)
        ax2.text(0.5, 0.44, f"Size: {s.sizing_pct:.1f}% (${s.notional_mm:.1f}mm)", transform=ax2.transAxes,
                 ha="center", fontsize=10)
        ax2.text(0.5, 0.34, f"Regime: {s.macro_regime}", transform=ax2.transAxes,
                 ha="center", fontsize=9, color="gray")

        # Active trade summary
        ax2.text(0.5, 0.18, f"Active trades: {len(active)}", transform=ax2.transAxes,
                 ha="center", fontsize=9)
        total_notional = sum(t.tranche_leg.notional_mm for t in active)
        ax2.text(0.5, 0.08, f"Total notional: ${total_notional:.1f}mm", transform=ax2.transAxes,
                 ha="center", fontsize=9)

    ax2.set_title("Signal Dashboard", fontweight="bold", fontsize=10)

    # --- Panel 3: Delta Hedge Visualization ---
    ax3 = fig.add_subplot(gs[0, 2])
    if active:
        trade_labels = []
        tranche_cs01s = []
        index_cs01s = []
        for t in active:
            tl = t.tranche_leg
            ih = t.index_hedge
            trade_labels.append(tl.tranche_label)
            t_dir = -1.0 if tl.is_long_protection else 1.0
            h_dir = -1.0 if ih.is_long_protection else 1.0
            tranche_cs01s.append(t_dir * tl.cs01_per_mm * tl.notional_mm / 1e6)
            index_cs01s.append(h_dir * ih.duration / 10000 * 1e6 * ih.notional_mm / 1e6)

        x = np.arange(len(trade_labels))
        width = 0.35
        ax3.bar(x - width / 2, tranche_cs01s, width, label="Tranche CS01",
                color="#e74c3c", edgecolor="white", alpha=0.8)
        ax3.bar(x + width / 2, index_cs01s, width, label="Index Hedge CS01",
                color="#2980b9", edgecolor="white", alpha=0.8)
        ax3.set_xticks(x)
        ax3.set_xticklabels(trade_labels, fontsize=8)
        ax3.axhline(0, color="black", linewidth=0.8)
        ax3.legend(fontsize=7)
        ax3.set_ylabel("CS01 ($)")
    ax3.set_title("Delta Hedge: Tranche vs Index CS01", fontweight="bold", fontsize=10)
    ax3.grid(True, alpha=0.3, axis="y")

    # --- Panel 4: Scenario Stress P&L Grouped Bar ---
    ax4 = fig.add_subplot(gs[1, :2])
    if stress_results:
        all_results = list(stress_results.values())[0] if stress_results else []
        if all_results:
            scenario_names = [r.scenario_name[:15] for r in all_results]
            spread_pnls = [r.spread_component for r in all_results]
            corr_pnls = [r.corr_component for r in all_results]
            default_pnls = [r.default_component for r in all_results]

            x = np.arange(len(scenario_names))
            width = 0.25
            ax4.bar(x - width, spread_pnls, width, label="Spread",
                    color="#2980b9", edgecolor="white", alpha=0.8)
            ax4.bar(x, corr_pnls, width, label="Correlation",
                    color="#8e44ad", edgecolor="white", alpha=0.8)
            ax4.bar(x + width, default_pnls, width, label="Default",
                    color="#e74c3c", edgecolor="white", alpha=0.8)
            ax4.set_xticks(x)
            ax4.set_xticklabels(scenario_names, fontsize=7, rotation=30, ha="right")
            ax4.axhline(0, color="black", linewidth=0.8)
            ax4.legend(fontsize=7)
            ax4.set_ylabel("P&L ($)")
    ax4.set_title("Stress Scenario P&L Decomposition", fontweight="bold", fontsize=10)
    ax4.grid(True, alpha=0.3, axis="y")

    # --- Panel 5: Net P&L per scenario bar ---
    ax5 = fig.add_subplot(gs[1, 2])
    if stress_results:
        all_results = list(stress_results.values())[0] if stress_results else []
        if all_results:
            names = [r.scenario_name[:12] for r in all_results]
            net_pnls = [r.net_pnl for r in all_results]
            colors = ["#2ecc71" if p >= 0 else "#e74c3c" for p in net_pnls]
            ax5.barh(range(len(names)), net_pnls, color=colors, edgecolor="white")
            ax5.set_yticks(range(len(names)))
            ax5.set_yticklabels(names, fontsize=7)
            ax5.axvline(0, color="black", linewidth=0.8)
            ax5.set_xlabel("Net P&L ($)")
    ax5.set_title("Net P&L per Scenario", fontweight="bold", fontsize=10)
    ax5.grid(True, alpha=0.3, axis="x")

    # --- Panel 6: Carry Analysis ---
    ax6 = fig.add_subplot(gs[2, 0])
    if carry_analysis:
        first_carry = list(carry_analysis.values())[0] if carry_analysis else {}
        if first_carry:
            periods = list(first_carry.keys())
            net_carries = [first_carry[p]["net_carry"] for p in periods]
            colors_carry = ["#2ecc71" if c >= 0 else "#e74c3c" for c in net_carries]
            ax6.bar(range(len(periods)), net_carries, color=colors_carry, edgecolor="white")
            ax6.set_xticks(range(len(periods)))
            ax6.set_xticklabels(periods, fontsize=8)
            ax6.axhline(0, color="black", linewidth=0.8)
            ax6.set_ylabel("Net Carry ($)")
    ax6.set_title("Carry Analysis by Period", fontweight="bold", fontsize=10)
    ax6.grid(True, alpha=0.3, axis="y")

    # --- Panel 7: Sensitivity Contour (Spread vs Correlation) ---
    ax7 = fig.add_subplot(gs[2, 1:])
    if active:
        t = active[0]
        tl = t.tranche_leg
        spread_range = np.linspace(-200, 400, 25)
        corr_range = np.linspace(-0.15, 0.30, 20)
        pnl_grid = np.zeros((len(corr_range), len(spread_range)))

        for i, dc in enumerate(corr_range):
            for j, ds in enumerate(spread_range):
                new_idx_spread = t.index_hedge.current_spread_bps + ds
                new_tr_spread = tl.current_fair_spread + ds * tl.delta_ratio
                new_corr = min(0.99, max(0.05, tl.current_base_corr + dc))
                pnl = compute_trade_pnl(t, new_idx_spread, new_tr_spread, new_corr, days=30)
                pnl_grid[i, j] = pnl["total"]

        cs = ax7.contourf(spread_range, corr_range * 100, pnl_grid, levels=15,
                           cmap="RdYlGn")
        fig.colorbar(cs, ax=ax7, label="P&L ($)")
        ax7.set_xlabel("Index Spread Change (bps)")
        ax7.set_ylabel("Correlation Change (%)")
        ax7.axhline(0, color="black", linewidth=0.5, linestyle="--")
        ax7.axvline(0, color="black", linewidth=0.5, linestyle="--")
    ax7.set_title("P&L Sensitivity: Spread vs Correlation", fontweight="bold", fontsize=10)

    plt.savefig("tranche_strategy_engine.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: tranche_strategy_engine.png")
    plt.close()
    return fig


# =============================================================================
# CSV EXPORT
# =============================================================================

def export_csv(trades: List[DispersionTrade],
                stress_results: Dict[str, List[StressResult]]):
    """Export strategy data to CSV files."""
    # 1. Trades summary
    rows = []
    for t in trades:
        tl = t.tranche_leg
        ih = t.index_hedge
        rows.append({
            "trade_id": t.trade_id,
            "strategy": t.strategy,
            "status": t.status,
            "index": tl.index_name,
            "tranche": tl.tranche_label,
            "tranche_notional_mm": tl.notional_mm,
            "index_notional_mm": ih.notional_mm,
            "delta_ratio": tl.delta_ratio,
            "net_cs01": t.net_cs01,
            "net_rho01": t.net_rho01,
            "net_theta_daily": t.net_theta_daily,
            "entry_fair_spread": tl.entry_fair_spread,
            "entry_base_corr": tl.entry_base_corr,
            "pnl_total": t.pnl_total,
        })
    pd.DataFrame(rows).to_csv("tranche_trades_summary.csv", index=False)
    print(f"  Exported: tranche_trades_summary.csv ({len(rows)} trades)")

    # 2. Stress test
    stress_rows = []
    for trade_id, results in stress_results.items():
        for r in results:
            stress_rows.append({
                "trade_id": trade_id,
                "scenario": r.scenario_name,
                "net_pnl": r.net_pnl,
                "pct_aum": r.net_pnl_pct_aum,
                "spread_component": r.spread_component,
                "corr_component": r.corr_component,
                "default_component": r.default_component,
            })
    pd.DataFrame(stress_rows).to_csv("tranche_stress_test.csv", index=False)
    print(f"  Exported: tranche_stress_test.csv ({len(stress_rows)} scenarios)")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run tranche strategy engine with sample trades."""
    print("\n" + "=" * 70)
    print("  TRANCHE STRATEGY ENGINE")
    print("  iTraxx Equity Tranche Dispersion Trading")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  AUM: ${DEFAULT_AUM/1e6:.0f}mm")

    # 1. Create sample trades
    print("\n  Constructing sample dispersion trades...")
    trade1 = create_sample_trade("LONG_DISPERSION", "Crossover")
    trade2 = create_sample_trade("LONG_DISPERSION", "Main")
    trades = [trade1, trade2]
    print(f"  Created {len(trades)} trades")
    for t in trades:
        print(f"    {t.trade_id}: {t.strategy} on {t.tranche_leg.index_name} "
              f"{t.tranche_leg.tranche_label}, notional ${t.tranche_leg.notional_mm:.1f}mm")

    # 2. Generate trade signals
    print("\n  Generating trade signals...")
    signals = generate_trade_signals(
        dispersion_score=-0.65,
        macro_regime="LOW_CORR",
        existing_trades=trades,
        aum=DEFAULT_AUM,
    )
    for s in signals:
        print(f"    {s.action}: {s.rationale}")

    # 3. Stress test
    print("\n  Running stress tests (8 scenarios)...")
    stress_results = {}
    for t in trades:
        results = stress_test_trade(t)
        stress_results[t.trade_id] = results
        worst = min(results, key=lambda x: x.net_pnl)
        best = max(results, key=lambda x: x.net_pnl)
        print(f"    {t.trade_id}: Best={best.scenario_name} (${best.net_pnl:+,.0f}), "
              f"Worst={worst.scenario_name} (${worst.net_pnl:+,.0f})")

    # 4. Carry analysis
    print("\n  Computing carry analysis...")
    carry_analysis = {}
    for t in trades:
        carry = compute_carry_analysis(t)
        carry_analysis[t.trade_id] = carry
        ann = carry.get("365d", {}).get("annualized_bps", 0)
        print(f"    {t.trade_id}: Annualized carry = {ann:.0f}bps")

    # 5. Print report
    print_report(trades, signals, stress_results, carry_analysis, DEFAULT_AUM)

    # 6. Plot dashboard
    print("\n  Generating chart...")
    plot_dashboard(trades, signals, stress_results, carry_analysis, DEFAULT_AUM)

    # 7. Export CSVs
    print("\n  Exporting CSV data...")
    export_csv(trades, stress_results)

    print(f"\n  DONE - Strategy engine complete")
    return trades, signals, stress_results


if __name__ == "__main__":
    main()
