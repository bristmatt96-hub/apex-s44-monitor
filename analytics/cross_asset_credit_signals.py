#!/usr/bin/env python3
"""
Cross-Asset Credit Signal Framework
=====================================
Uses equity vol, rates, FX, and commodity signals to position in European credit.
Includes a Merton-based fair value spread model and dislocation detection.

Focus: iTraxx Main (IG) & iTraxx Crossover (HY)

Signal Modules:
  1. EQUITY VOL   - VIX level/term structure, realized vs implied, vol regime
  2. RATES         - Curve shape, real rates, rate of change, BTP-Bund
  3. FX            - EUR/USD, dollar strength, EM FX stress, carry
  4. EQUITY        - S&P500 momentum, drawdown, equity-credit dislocation (Merton)
  5. COMMODITIES   - Oil, copper/gold ratio (growth proxy)

Output:
  - Per-module signal score (-2 to +2: strong short to strong long credit)
  - Composite positioning signal
  - Dislocation alerts (credit too tight/wide vs cross-asset fair value)
  - Historical backtest of signal vs actual EUR HY spread changes

Usage:
  pip install fredapi pandas matplotlib numpy scipy
  set FRED_API_KEY=your_key_here
  python cross_asset_credit_signals.py
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
from scipy import stats

warnings.filterwarnings("ignore")


# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_YEARS = 12
START_DATE = datetime.now() - timedelta(days=365 * HISTORY_YEARS)
ZSCORE_WINDOW = 252 * 3  # 3 years of daily data for Z-scores
SIGNAL_LOOKBACK = 63     # ~3 months for momentum signals


# =============================================================================
# FRED SERIES REGISTRY
# =============================================================================

SERIES = {
    # --- Equity Vol ---
    "VIX":          {"id": "VIXCLS",          "desc": "VIX",                          "freq": "D"},
    "VIX3M":        {"id": "VXVCLS",          "desc": "VIX 3-Month",                  "freq": "D"},

    # --- Equity ---
    "SPX":          {"id": "SP500",           "desc": "S&P 500",                      "freq": "D"},

    # --- Rates ---
    "UST_2Y":       {"id": "DGS2",            "desc": "US 2Y Treasury",               "freq": "D"},
    "UST_5Y":       {"id": "DGS5",            "desc": "US 5Y Treasury",               "freq": "D"},
    "UST_10Y":      {"id": "DGS10",           "desc": "US 10Y Treasury",              "freq": "D"},
    "UST_30Y":      {"id": "DGS30",           "desc": "US 30Y Treasury",              "freq": "D"},
    "TIPS_5Y":      {"id": "DFII5",           "desc": "US 5Y TIPS Real Yield",        "freq": "D"},
    "TIPS_10Y":     {"id": "DFII10",          "desc": "US 10Y TIPS Real Yield",       "freq": "D"},
    "BUND_10Y":     {"id": "IRLTLT01DEM156N", "desc": "German Bund 10Y",              "freq": "M"},
    "BTP_10Y":      {"id": "IRLTLT01ITM156N", "desc": "Italy BTP 10Y",                "freq": "M"},

    # --- FX ---
    "EURUSD":       {"id": "DEXUSEU",         "desc": "EUR/USD",                      "freq": "D"},
    "USDJPY":       {"id": "DEXJPUS",         "desc": "USD/JPY (inverted on FRED)",   "freq": "D"},
    "DXY":          {"id": "DTWEXBGS",        "desc": "Broad USD Index",              "freq": "D"},
    "EM_FX":        {"id": "DTWEXEMEGS",      "desc": "EM USD Index",                 "freq": "D"},

    # --- Credit Spreads ---
    "EUR_HY_OAS":   {"id": "BAMLHE00EHYIOAS", "desc": "Euro HY OAS",                 "freq": "D"},
    "US_HY_OAS":    {"id": "BAMLH0A0HYM2",    "desc": "US HY OAS",                   "freq": "D"},
    "US_IG_OAS":    {"id": "BAMLC0A0CM",       "desc": "US IG OAS",                   "freq": "D"},
    "US_BB_OAS":    {"id": "BAMLH0A1HYBB",     "desc": "US BB OAS",                   "freq": "D"},
    "US_B_OAS":     {"id": "BAMLH0A2HYB",      "desc": "US B OAS",                    "freq": "D"},
    "US_CCC_OAS":   {"id": "BAMLH0A3HYC",      "desc": "US CCC OAS",                  "freq": "D"},

    # --- Commodities ---
    "WTI":          {"id": "DCOILWTICO",       "desc": "WTI Crude Oil",               "freq": "D"},
    "BRENT":        {"id": "DCOILBRENTEU",     "desc": "Brent Crude Oil",             "freq": "D"},
    "GOLD":         {"id": "NASDAQQGLDI",      "desc": "Gold (NASDAQ Gold Index)",     "freq": "D"},
    "COPPER":       {"id": "PCOPPUSDM",        "desc": "Copper Price",                "freq": "M"},
}


# =============================================================================
# DATA FETCHING
# =============================================================================


def fetch_data() -> pd.DataFrame:
    """Fetch all series from FRED, align to daily business-day frequency."""
    from fredapi import Fred

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("ERROR: Set FRED_API_KEY environment variable.")
        print("  Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")
        sys.exit(1)

    fred = Fred(api_key=api_key)
    frames = {}

    print("=" * 70)
    print("  FETCHING CROSS-ASSET DATA FROM FRED")
    print("=" * 70)

    for key, meta in SERIES.items():
        try:
            s = fred.get_series(meta["id"], observation_start=START_DATE)
            frames[key] = s
            n = len(s.dropna())
            latest = s.dropna().iloc[-1] if n > 0 else "N/A"
            dt = s.dropna().index[-1].strftime("%Y-%m-%d") if n > 0 else "N/A"
            print(f"  [OK]   {meta['desc']:35s} ({meta['id']:20s}) | {dt} = {latest}")
        except Exception as e:
            print(f"  [FAIL] {meta['desc']:35s} ({meta['id']:20s}) | {e}")
            frames[key] = pd.Series(dtype=float)

    df = pd.DataFrame(frames)
    df.index = pd.to_datetime(df.index)
    # Resample to business-day, forward-fill (monthly series get daily interpolation)
    df = df.resample("B").last().ffill(limit=10)
    return df


# =============================================================================
# DERIVED SERIES
# =============================================================================


def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Compute derived series from raw data."""

    # --- Rates ---
    if "UST_10Y" in df and "UST_2Y" in df:
        df["US_2S10S"] = df["UST_10Y"] - df["UST_2Y"]
    if "UST_10Y" in df and "UST_5Y" in df:
        df["US_5S10S"] = df["UST_10Y"] - df["UST_5Y"]
    if "UST_30Y" in df and "UST_10Y" in df:
        df["US_10S30S"] = df["UST_30Y"] - df["UST_10Y"]
    if "TIPS_5Y" in df and "UST_5Y" in df:
        df["US_5Y_BREAKEVEN"] = df["UST_5Y"] - df["TIPS_5Y"]

    # BTP-Bund spread (Euro periphery risk)
    if "BTP_10Y" in df and "BUND_10Y" in df:
        df["BTP_BUND"] = df["BTP_10Y"] - df["BUND_10Y"]

    # --- Vol ---
    if "VIX" in df and "VIX3M" in df:
        df["VIX_TERM_STRUCTURE"] = df["VIX"] / df["VIX3M"]
        # < 1 = contango (normal), > 1 = backwardation (stress)

    # SPX realized vol (21-day annualized)
    if "SPX" in df:
        df["SPX_RVOL_21D"] = df["SPX"].pct_change().rolling(21).std() * np.sqrt(252) * 100
        df["SPX_RVOL_63D"] = df["SPX"].pct_change().rolling(63).std() * np.sqrt(252) * 100
        # VIX vs realized = vol risk premium
        if "VIX" in df:
            df["VOL_RISK_PREMIUM"] = df["VIX"] - df["SPX_RVOL_21D"]

        # SPX drawdown from rolling 52-week high
        df["SPX_52W_HIGH"] = df["SPX"].rolling(252).max()
        df["SPX_DRAWDOWN"] = (df["SPX"] / df["SPX_52W_HIGH"] - 1) * 100

        # SPX momentum (63-day return)
        df["SPX_MOM_63D"] = df["SPX"].pct_change(63) * 100

    # --- FX ---
    if "EURUSD" in df:
        df["EURUSD_MOM_63D"] = df["EURUSD"].pct_change(63) * 100
    if "DXY" in df:
        df["DXY_MOM_63D"] = df["DXY"].pct_change(63) * 100
    if "EM_FX" in df:
        df["EMFX_MOM_63D"] = df["EM_FX"].pct_change(63) * 100

    # --- Commodities ---
    if "COPPER" in df and "GOLD" in df:
        df["COPPER_GOLD"] = df["COPPER"] / df["GOLD"]
        # Rising = growth, falling = defensives winning

    if "WTI" in df:
        df["WTI_MOM_63D"] = df["WTI"].pct_change(63) * 100

    # --- Credit ---
    if "US_HY_OAS" in df and "US_IG_OAS" in df:
        df["HY_IG_RATIO"] = df["US_HY_OAS"] / df["US_IG_OAS"]

    if "US_CCC_OAS" in df and "US_BB_OAS" in df:
        df["CCC_BB_RATIO"] = df["US_CCC_OAS"] / df["US_BB_OAS"]

    if "EUR_HY_OAS" in df and "US_HY_OAS" in df:
        df["EUR_US_HY_RATIO"] = df["EUR_HY_OAS"] / df["US_HY_OAS"]

    return df


# =============================================================================
# SIGNAL MODULES
# =============================================================================
# Each module returns a signal from -2 (strong short credit) to +2 (strong long credit)


def _zscore(series: pd.Series, window: int = ZSCORE_WINDOW) -> pd.Series:
    """Rolling Z-score."""
    m = series.rolling(window, min_periods=min(window // 2, 126)).mean()
    s = series.rolling(window, min_periods=min(window // 2, 126)).std().replace(0, np.nan)
    return (series - m) / s


def _score_zscore(z: float, thresholds: Tuple[float, ...] = (-1.5, -0.5, 0.5, 1.5)) -> int:
    """Convert Z-score to signal: -2, -1, 0, +1, +2."""
    if pd.isna(z):
        return 0
    if z <= thresholds[0]:
        return -2
    elif z <= thresholds[1]:
        return -1
    elif z <= thresholds[2]:
        return 0
    elif z <= thresholds[3]:
        return 1
    else:
        return 2


def signal_equity_vol(df: pd.DataFrame) -> Dict:
    """
    Equity Vol Signal Module
    ========================
    Logic:
    - High VIX = short credit (buy protection)
    - VIX term structure backwardation = stress = short credit
    - Large vol risk premium = complacency risk
    - Low realized vol = supportive for credit (but watch for vol compression snap)
    """
    signals = {}
    details = {}

    # VIX level Z-score (inverted: high VIX = negative for credit)
    if "VIX" in df:
        vix_z = _zscore(df["VIX"])
        latest_z = vix_z.dropna().iloc[-1] if len(vix_z.dropna()) > 0 else 0
        signals["VIX_level"] = -_score_zscore(latest_z)  # invert: high VIX = bad
        details["VIX"] = f"{df['VIX'].dropna().iloc[-1]:.1f} (Z={latest_z:+.2f})"

    # VIX term structure
    if "VIX_TERM_STRUCTURE" in df:
        ts = df["VIX_TERM_STRUCTURE"].dropna()
        if len(ts) > 0:
            latest_ts = ts.iloc[-1]
            # > 1.0 = backwardation (panic), < 0.85 = extreme contango (complacent)
            if latest_ts > 1.05:
                signals["VIX_term_structure"] = -2
            elif latest_ts > 1.0:
                signals["VIX_term_structure"] = -1
            elif latest_ts > 0.85:
                signals["VIX_term_structure"] = 1
            else:
                signals["VIX_term_structure"] = 0  # extreme contango can precede snap
            details["VIX_TS"] = f"{latest_ts:.3f} ({'backwardation' if latest_ts > 1 else 'contango'})"

    # Vol risk premium
    if "VOL_RISK_PREMIUM" in df:
        vrp = df["VOL_RISK_PREMIUM"].dropna()
        if len(vrp) > 0:
            vrp_z = _zscore(df["VOL_RISK_PREMIUM"])
            latest_vrp_z = vrp_z.dropna().iloc[-1] if len(vrp_z.dropna()) > 0 else 0
            # High VRP = market paying a lot for protection = fear = eventually bullish
            # Low VRP = complacency
            signals["vol_risk_premium"] = _score_zscore(latest_vrp_z, (-1.0, -0.3, 0.3, 1.0))
            details["VRP"] = f"{vrp.iloc[-1]:.1f}pts (Z={latest_vrp_z:+.2f})"

    # Composite
    if signals:
        weights = {"VIX_level": 2.0, "VIX_term_structure": 1.5, "vol_risk_premium": 1.0}
        total_w = sum(weights.get(k, 1.0) for k in signals)
        composite = sum(signals[k] * weights.get(k, 1.0) for k in signals) / total_w
    else:
        composite = 0

    return {
        "name": "EQUITY VOL",
        "signal": round(composite, 2),
        "sub_signals": signals,
        "details": details,
        "weight": 2.0,  # vol is the #1 driver of short-term credit moves
    }


def signal_rates(df: pd.DataFrame) -> Dict:
    """
    Rates Signal Module
    ===================
    Logic:
    - Flattening/inverting curve = late cycle = caution
    - Rising real rates = tighter financial conditions = negative
    - BTP-Bund widening = Euro stress = negative for Xover
    - Rapidly rising rates = negative; falling rates (from high) = positive
    """
    signals = {}
    details = {}

    # 2s10s slope Z-score
    if "US_2S10S" in df:
        slope_z = _zscore(df["US_2S10S"])
        latest_z = slope_z.dropna().iloc[-1] if len(slope_z.dropna()) > 0 else 0
        latest_val = df["US_2S10S"].dropna().iloc[-1] if len(df["US_2S10S"].dropna()) > 0 else 0
        # Positive slope = good for credit, inverted = bad
        signals["US_2s10s"] = _score_zscore(latest_z)
        details["2s10s"] = f"{latest_val:.0f}bps (Z={latest_z:+.2f})"

    # Real rates (5Y TIPS) - higher = tighter conditions
    if "TIPS_5Y" in df:
        tips_z = _zscore(df["TIPS_5Y"])
        latest_z = tips_z.dropna().iloc[-1] if len(tips_z.dropna()) > 0 else 0
        latest_val = df["TIPS_5Y"].dropna().iloc[-1] if len(df["TIPS_5Y"].dropna()) > 0 else 0
        signals["real_rates_5Y"] = -_score_zscore(latest_z)  # higher real = bad
        details["5Y_real"] = f"{latest_val:.2f}% (Z={latest_z:+.2f})"

    # Rate of change in 10Y (3-month change)
    if "UST_10Y" in df:
        rate_chg = df["UST_10Y"].diff(63)  # ~3 month change in yield
        rate_chg_z = _zscore(rate_chg)
        latest_z = rate_chg_z.dropna().iloc[-1] if len(rate_chg_z.dropna()) > 0 else 0
        latest_chg = rate_chg.dropna().iloc[-1] if len(rate_chg.dropna()) > 0 else 0
        # Rapidly rising rates = negative for credit
        signals["rate_velocity"] = -_score_zscore(latest_z, (-1.0, -0.3, 0.3, 1.0))
        details["10Y_3m_chg"] = f"{latest_chg:+.0f}bps (Z={latest_z:+.2f})"

    # BTP-Bund spread (Euro periphery stress)
    if "BTP_BUND" in df:
        btp_z = _zscore(df["BTP_BUND"])
        latest_z = btp_z.dropna().iloc[-1] if len(btp_z.dropna()) > 0 else 0
        latest_val = df["BTP_BUND"].dropna().iloc[-1] if len(df["BTP_BUND"].dropna()) > 0 else 0
        signals["BTP_Bund"] = -_score_zscore(latest_z)  # wider = bad for Euro credit
        details["BTP-Bund"] = f"{latest_val*100:.0f}bps (Z={latest_z:+.2f})"

    # Breakevens (growth/inflation expectations)
    if "US_5Y_BREAKEVEN" in df:
        be_z = _zscore(df["US_5Y_BREAKEVEN"])
        latest_z = be_z.dropna().iloc[-1] if len(be_z.dropna()) > 0 else 0
        # Moderate breakevens = healthy; collapsing = deflation fear = bad
        signals["breakevens"] = _score_zscore(latest_z, (-1.5, -0.5, 0.5, 1.5))
        details["5Y_BE"] = f"{df['US_5Y_BREAKEVEN'].dropna().iloc[-1]:.2f}% (Z={latest_z:+.2f})"

    if signals:
        weights = {"US_2s10s": 1.5, "real_rates_5Y": 1.5, "rate_velocity": 1.2, "BTP_Bund": 2.0, "breakevens": 0.8}
        total_w = sum(weights.get(k, 1.0) for k in signals)
        composite = sum(signals[k] * weights.get(k, 1.0) for k in signals) / total_w
    else:
        composite = 0

    return {
        "name": "RATES",
        "signal": round(composite, 2),
        "sub_signals": signals,
        "details": details,
        "weight": 1.5,
    }


def signal_fx(df: pd.DataFrame) -> Dict:
    """
    FX Signal Module
    ================
    Logic:
    - Strong USD = tighter global financial conditions = negative for credit (esp EM & Euro)
    - EUR/USD weakness = Euro corporate stress, capital outflows
    - EM FX stress = risk-off = contagion to European credit
    - JPY strength = risk-off proxy
    """
    signals = {}
    details = {}

    # USD Broad Index momentum (inverted: strong USD = bad for credit)
    if "DXY_MOM_63D" in df:
        dxy_z = _zscore(df["DXY_MOM_63D"])
        latest_z = dxy_z.dropna().iloc[-1] if len(dxy_z.dropna()) > 0 else 0
        latest_val = df["DXY_MOM_63D"].dropna().iloc[-1] if len(df["DXY_MOM_63D"].dropna()) > 0 else 0
        signals["USD_momentum"] = -_score_zscore(latest_z)  # strong USD = bad
        details["DXY_3m"] = f"{latest_val:+.1f}% (Z={latest_z:+.2f})"

    # EUR/USD momentum
    if "EURUSD_MOM_63D" in df:
        eur_z = _zscore(df["EURUSD_MOM_63D"])
        latest_z = eur_z.dropna().iloc[-1] if len(eur_z.dropna()) > 0 else 0
        latest_val = df["EURUSD_MOM_63D"].dropna().iloc[-1] if len(df["EURUSD_MOM_63D"].dropna()) > 0 else 0
        signals["EURUSD_momentum"] = _score_zscore(latest_z)  # strong EUR = good for Euro credit
        details["EURUSD_3m"] = f"{latest_val:+.1f}% (Z={latest_z:+.2f})"

    # EM FX stress (EM USD index rising = EM weakening = stress)
    if "EMFX_MOM_63D" in df:
        emfx_z = _zscore(df["EMFX_MOM_63D"])
        latest_z = emfx_z.dropna().iloc[-1] if len(emfx_z.dropna()) > 0 else 0
        latest_val = df["EMFX_MOM_63D"].dropna().iloc[-1] if len(df["EMFX_MOM_63D"].dropna()) > 0 else 0
        # Rising EM USD index = EM currencies weakening = stress
        signals["EM_FX_stress"] = -_score_zscore(latest_z)
        details["EMFX_3m"] = f"{latest_val:+.1f}% (Z={latest_z:+.2f})"

    # JPY as risk-off proxy (JPY strengthening = USDJPY falling = risk-off)
    if "USDJPY" in df:
        jpy_mom = df["USDJPY"].pct_change(63) * 100
        jpy_z = _zscore(jpy_mom)
        latest_z = jpy_z.dropna().iloc[-1] if len(jpy_z.dropna()) > 0 else 0
        latest_val = jpy_mom.dropna().iloc[-1] if len(jpy_mom.dropna()) > 0 else 0
        # USDJPY falling (negative mom) = JPY strengthening = risk-off = bad
        signals["JPY_risk_off"] = _score_zscore(latest_z, (-1.0, -0.3, 0.3, 1.0))
        details["USDJPY_3m"] = f"{latest_val:+.1f}% (Z={latest_z:+.2f})"

    if signals:
        weights = {"USD_momentum": 1.5, "EURUSD_momentum": 1.0, "EM_FX_stress": 1.5, "JPY_risk_off": 1.0}
        total_w = sum(weights.get(k, 1.0) for k in signals)
        composite = sum(signals[k] * weights.get(k, 1.0) for k in signals) / total_w
    else:
        composite = 0

    return {
        "name": "FX",
        "signal": round(composite, 2),
        "sub_signals": signals,
        "details": details,
        "weight": 1.2,
    }


def signal_equity(df: pd.DataFrame) -> Dict:
    """
    Equity Signal Module
    ====================
    Logic:
    - SPX positive momentum = risk-on = supportive for credit
    - SPX drawdown = risk-off = negative for credit
    - Equity-credit dislocation: when equities rally but credit doesn't follow (or vice versa)
    """
    signals = {}
    details = {}

    # SPX momentum
    if "SPX_MOM_63D" in df:
        spx_z = _zscore(df["SPX_MOM_63D"])
        latest_z = spx_z.dropna().iloc[-1] if len(spx_z.dropna()) > 0 else 0
        latest_val = df["SPX_MOM_63D"].dropna().iloc[-1] if len(df["SPX_MOM_63D"].dropna()) > 0 else 0
        signals["SPX_momentum"] = _score_zscore(latest_z)
        details["SPX_3m"] = f"{latest_val:+.1f}% (Z={latest_z:+.2f})"

    # SPX drawdown (how far from 52-week high)
    if "SPX_DRAWDOWN" in df:
        dd = df["SPX_DRAWDOWN"].dropna()
        if len(dd) > 0:
            latest_dd = dd.iloc[-1]
            if latest_dd < -20:
                signals["SPX_drawdown"] = -2
            elif latest_dd < -10:
                signals["SPX_drawdown"] = -1
            elif latest_dd < -5:
                signals["SPX_drawdown"] = 0
            else:
                signals["SPX_drawdown"] = 1
            details["SPX_DD"] = f"{latest_dd:.1f}% from 52w high"

    if signals:
        weights = {"SPX_momentum": 1.5, "SPX_drawdown": 1.0}
        total_w = sum(weights.get(k, 1.0) for k in signals)
        composite = sum(signals[k] * weights.get(k, 1.0) for k in signals) / total_w
    else:
        composite = 0

    return {
        "name": "EQUITY",
        "signal": round(composite, 2),
        "sub_signals": signals,
        "details": details,
        "weight": 1.5,
    }


def signal_commodities(df: pd.DataFrame) -> Dict:
    """
    Commodity Signal Module
    =======================
    Logic:
    - Copper/Gold ratio rising = growth > defensives = risk-on = good for credit
    - Oil crashing = demand destruction = bad for credit (especially HY energy)
    - Oil spiking = cost push = mixed (bad for margins, but good for energy credits)
    """
    signals = {}
    details = {}

    # Copper/Gold ratio
    if "COPPER_GOLD" in df:
        cg_z = _zscore(df["COPPER_GOLD"])
        latest_z = cg_z.dropna().iloc[-1] if len(cg_z.dropna()) > 0 else 0
        latest_val = df["COPPER_GOLD"].dropna().iloc[-1] if len(df["COPPER_GOLD"].dropna()) > 0 else 0
        signals["copper_gold"] = _score_zscore(latest_z)
        details["Cu/Au"] = f"{latest_val:.2f} (Z={latest_z:+.2f})"

    # WTI oil momentum
    if "WTI_MOM_63D" in df:
        oil_z = _zscore(df["WTI_MOM_63D"])
        latest_z = oil_z.dropna().iloc[-1] if len(oil_z.dropna()) > 0 else 0
        latest_val = df["WTI_MOM_63D"].dropna().iloc[-1] if len(df["WTI_MOM_63D"].dropna()) > 0 else 0
        # Moderate oil positive = ok; crashing = bad; spiking = also bad
        if latest_z < -1.5:
            signals["oil_momentum"] = -2  # crashing = demand destruction
        elif latest_z < -0.5:
            signals["oil_momentum"] = -1
        elif latest_z > 1.5:
            signals["oil_momentum"] = -1  # spiking = cost push
        elif latest_z > 0.5:
            signals["oil_momentum"] = 0
        else:
            signals["oil_momentum"] = 1  # stable/moderate = good
        details["WTI_3m"] = f"{latest_val:+.1f}% (Z={latest_z:+.2f})"

    if signals:
        weights = {"copper_gold": 1.5, "oil_momentum": 1.0}
        total_w = sum(weights.get(k, 1.0) for k in signals)
        composite = sum(signals[k] * weights.get(k, 1.0) for k in signals) / total_w
    else:
        composite = 0

    return {
        "name": "COMMODITIES",
        "signal": round(composite, 2),
        "sub_signals": signals,
        "details": details,
        "weight": 0.8,
    }


# =============================================================================
# MERTON-STYLE EQUITY-CREDIT DISLOCATION MODEL
# =============================================================================


def merton_dislocation(df: pd.DataFrame, window: int = 504) -> Dict:
    """
    Simplified Merton Model: Equity-Credit Dislocation Detector
    ============================================================
    In Merton's framework, credit spreads are a function of:
      - Asset volatility (proxy: equity realized vol)
      - Leverage (not directly observable, we use spread/vol ratio)
      - Distance to default (equity level vs debt)

    We use a rolling regression of EUR HY spreads on SPX vol + SPX level
    to estimate "fair value" spreads, then flag dislocations.

    A positive residual = credit is WIDER than equity implies = potential LONG credit
    A negative residual = credit is TIGHTER than equity implies = potential SHORT credit
    """
    result = {"name": "MERTON DISLOCATION", "dislocation": 0, "details": {}}

    required = ["EUR_HY_OAS", "SPX_RVOL_63D", "SPX"]
    if not all(col in df.columns for col in required):
        result["details"]["status"] = "Missing required series"
        return result

    # Build the model data
    model_df = df[required].dropna()
    if len(model_df) < window:
        result["details"]["status"] = f"Insufficient data ({len(model_df)} < {window})"
        return result

    # Normalize inputs
    y = model_df["EUR_HY_OAS"]
    x1 = model_df["SPX_RVOL_63D"]
    x2 = model_df["SPX"].pct_change(63) * -100  # equity weakness = positive (spread widening factor)
    x2 = x2.fillna(0)

    # Rolling regression (last N days)
    y_train = y.iloc[-window:]
    x1_train = x1.iloc[-window:]
    x2_train = x2.iloc[-window:]

    # Simple OLS: spread = a + b1*vol + b2*equity_weakness
    X = np.column_stack([np.ones(len(y_train)), x1_train.values, x2_train.values])
    Y = y_train.values

    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        result["details"]["status"] = "Regression failed"
        return result

    # Fair value = predicted spread
    fair_value = beta[0] + beta[1] * x1.iloc[-1] + beta[2] * x2.iloc[-1]
    actual = y.iloc[-1]
    residual = actual - fair_value
    residual_pct = (residual / fair_value) * 100

    # Historical residual distribution for Z-score
    fitted_all = beta[0] + beta[1] * x1_train.values + beta[2] * x2_train.values
    residuals_hist = y_train.values - fitted_all
    residual_z = (residual - np.mean(residuals_hist)) / np.std(residuals_hist)

    # Dislocation signal
    if residual_z > 1.5:
        dislocation = 2   # credit MUCH wider than equity implies -> BUY credit
    elif residual_z > 0.75:
        dislocation = 1   # credit somewhat wider -> lean long
    elif residual_z < -1.5:
        dislocation = -2  # credit MUCH tighter than equity implies -> SELL credit
    elif residual_z < -0.75:
        dislocation = -1  # credit somewhat tight -> lean short
    else:
        dislocation = 0   # no dislocation

    result["dislocation"] = dislocation
    result["signal"] = dislocation
    result["weight"] = 1.5
    result["details"] = {
        "actual_OAS": f"{actual:.0f}bps",
        "fair_value_OAS": f"{fair_value:.0f}bps",
        "residual": f"{residual:+.0f}bps ({residual_pct:+.1f}%)",
        "residual_Z": f"{residual_z:+.2f}",
        "model_R2": f"{1 - np.var(residuals_hist) / np.var(y_train.values):.2f}",
        "interpretation": (
            "Credit CHEAP vs equity (BUY opportunity)" if dislocation > 0
            else "Credit RICH vs equity (SELL/hedge)" if dislocation < 0
            else "No significant dislocation"
        ),
    }
    result["sub_signals"] = {"merton_residual": dislocation}

    return result


# =============================================================================
# COMPOSITE SIGNAL
# =============================================================================


def compute_composite(modules: List[Dict]) -> Dict:
    """Weighted composite of all signal modules."""
    total_weight = 0
    weighted_sum = 0

    for m in modules:
        w = m.get("weight", 1.0)
        s = m.get("signal", 0)
        weighted_sum += s * w
        total_weight += w

    composite = weighted_sum / total_weight if total_weight > 0 else 0

    # Map to positioning
    if composite > 1.0:
        position = "STRONG LONG CREDIT (sell protection aggressively)"
    elif composite > 0.5:
        position = "LONG CREDIT (sell protection, overweight Xover)"
    elif composite > 0.15:
        position = "LEAN LONG (small sell protection bias)"
    elif composite > -0.15:
        position = "NEUTRAL (carry only, no directional bias)"
    elif composite > -0.5:
        position = "LEAN SHORT (small buy protection bias)"
    elif composite > -1.0:
        position = "SHORT CREDIT (buy protection, underweight Xover)"
    else:
        position = "STRONG SHORT CREDIT (buy protection aggressively)"

    return {
        "composite": round(composite, 3),
        "position": position,
        "module_signals": {m["name"]: m.get("signal", 0) for m in modules},
        "module_weights": {m["name"]: m.get("weight", 1.0) for m in modules},
    }


# =============================================================================
# HISTORICAL BACKTEST
# =============================================================================


def backtest_composite_signal(df: pd.DataFrame, lookback_days: int = 63) -> pd.DataFrame:
    """
    Run the composite signal historically and compare to subsequent EUR HY spread changes.
    This gives you a sense of signal quality over time.

    Returns a DataFrame with signal vs forward spread change.
    """
    if "EUR_HY_OAS" not in df.columns:
        return pd.DataFrame()

    # Forward spread change (63-day)
    df["EUR_HY_FWD_CHG"] = df["EUR_HY_OAS"].shift(-lookback_days) - df["EUR_HY_OAS"]

    # We need to compute signals at each point in time
    # For efficiency, compute key Z-score-based signals as time series

    signals_ts = pd.DataFrame(index=df.index)

    # VIX signal (inverted)
    if "VIX" in df:
        signals_ts["vol"] = -_zscore(df["VIX"])

    # SPX momentum signal
    if "SPX_MOM_63D" in df:
        signals_ts["equity"] = _zscore(df["SPX_MOM_63D"])

    # Curve signal
    if "US_2S10S" in df:
        signals_ts["curve"] = _zscore(df["US_2S10S"])

    # USD signal (inverted)
    if "DXY_MOM_63D" in df:
        signals_ts["fx"] = -_zscore(df["DXY_MOM_63D"])

    # Copper/gold
    if "COPPER_GOLD" in df:
        signals_ts["commodities"] = _zscore(df["COPPER_GOLD"])

    # Composite
    signals_ts["composite"] = signals_ts.mean(axis=1)

    # Combine with forward spread change
    bt = pd.DataFrame({
        "signal": signals_ts["composite"],
        "fwd_spread_chg": df["EUR_HY_FWD_CHG"],
    }).dropna()

    return bt


# =============================================================================
# VISUALIZATION
# =============================================================================


def plot_dashboard(df: pd.DataFrame, modules: List[Dict], composite: Dict, backtest: pd.DataFrame):
    """Full cross-asset credit signal dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "CROSS-ASSET CREDIT SIGNAL FRAMEWORK - iTraxx Focus",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Data: FRED",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(4, 4, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # --- Panel 1: EUR HY OAS + Composite Signal Overlay ---
    ax1 = fig.add_subplot(gs[0, :3])
    if "EUR_HY_OAS" in df:
        spread = df["EUR_HY_OAS"].dropna()
        ax1.plot(spread.index, spread.values, color="black", linewidth=1.2, label="Euro HY OAS (bps)")
        ax1.set_ylabel("OAS (bps)", color="black")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)
    ax1.set_title("Euro HY OAS vs Cross-Asset Composite Signal", fontweight="bold")

    # Overlay composite signal as color bands
    if len(backtest) > 0:
        ax1b = ax1.twinx()
        sig = backtest["signal"]
        ax1b.fill_between(sig.index, 0, sig.values, where=sig > 0, alpha=0.15, color="green", label="Long signal")
        ax1b.fill_between(sig.index, 0, sig.values, where=sig < 0, alpha=0.15, color="red", label="Short signal")
        ax1b.set_ylabel("Composite Signal", color="gray")
        ax1b.legend(loc="upper right")

    # --- Panel 2: Current Signal Gauge ---
    ax_gauge = fig.add_subplot(gs[0, 3])
    ax_gauge.set_xlim(-2.5, 2.5)
    ax_gauge.set_ylim(0, 1)
    ax_gauge.axis("off")

    comp_val = composite["composite"]
    color = "#2ecc71" if comp_val > 0.5 else "#e74c3c" if comp_val < -0.5 else "#f39c12"

    box = FancyBboxPatch(
        (-2.3, 0.1), 4.6, 0.8,
        boxstyle="round,pad=0.05",
        facecolor=color, alpha=0.2, edgecolor=color, linewidth=3,
    )
    ax_gauge.add_patch(box)
    ax_gauge.text(0, 0.75, "COMPOSITE SIGNAL", ha="center", va="center", fontsize=11, fontweight="bold")
    ax_gauge.text(0, 0.55, f"{comp_val:+.2f}", ha="center", va="center", fontsize=28, fontweight="bold", color=color)
    # Wrap long position text
    pos_text = composite["position"]
    ax_gauge.text(0, 0.30, pos_text, ha="center", va="center", fontsize=7, wrap=True, style="italic")

    # Module breakdown
    y_pos = 0.18
    for name, sig in composite["module_signals"].items():
        c = "#2ecc71" if sig > 0.3 else "#e74c3c" if sig < -0.3 else "#95a5a6"
        ax_gauge.text(-2.0, y_pos, f"{name[:12]:12s}", fontsize=6, va="center")
        ax_gauge.text(1.2, y_pos, f"{sig:+.1f}", fontsize=7, va="center", color=c, fontweight="bold")
        y_pos -= 0.04

    # --- Panel 3: VIX + Term Structure ---
    ax2 = fig.add_subplot(gs[1, 0])
    if "VIX" in df:
        s = df["VIX"].dropna()
        ax2.plot(s.index, s.values, color="#8e44ad", linewidth=1)
        ax2.axhline(20, color="orange", linewidth=0.7, linestyle="--")
        ax2.axhline(30, color="red", linewidth=0.7, linestyle="--")
        ax2.set_title("VIX", fontweight="bold", fontsize=10)
        ax2.grid(True, alpha=0.3)

    ax3 = fig.add_subplot(gs[1, 1])
    if "VIX_TERM_STRUCTURE" in df:
        s = df["VIX_TERM_STRUCTURE"].dropna()
        ax3.plot(s.index, s.values, color="#2c3e50", linewidth=1)
        ax3.axhline(1.0, color="red", linewidth=0.8, linestyle="--", label="Backwardation line")
        ax3.set_title("VIX / VIX3M (Term Structure)", fontweight="bold", fontsize=10)
        ax3.legend(fontsize=7)
        ax3.grid(True, alpha=0.3)

    # --- Panel 4: Rates ---
    ax4 = fig.add_subplot(gs[1, 2])
    if "US_2S10S" in df:
        s = df["US_2S10S"].dropna()
        ax4.plot(s.index, s.values, color="#2980b9", linewidth=1)
        ax4.axhline(0, color="red", linewidth=0.8, linestyle="--")
        ax4.set_title("US 2s10s Curve (bps)", fontweight="bold", fontsize=10)
        ax4.grid(True, alpha=0.3)

    ax5 = fig.add_subplot(gs[1, 3])
    if "BTP_BUND" in df:
        s = (df["BTP_BUND"] * 100).dropna()
        ax5.plot(s.index, s.values, color="#e74c3c", linewidth=1)
        ax5.set_title("BTP-Bund Spread (bps)", fontweight="bold", fontsize=10)
        ax5.grid(True, alpha=0.3)

    # --- Panel 5: FX ---
    ax6 = fig.add_subplot(gs[2, 0])
    if "EURUSD" in df:
        s = df["EURUSD"].dropna()
        ax6.plot(s.index, s.values, color="#27ae60", linewidth=1)
        ax6.set_title("EUR/USD", fontweight="bold", fontsize=10)
        ax6.grid(True, alpha=0.3)

    ax7 = fig.add_subplot(gs[2, 1])
    if "DXY" in df:
        s = df["DXY"].dropna()
        ax7.plot(s.index, s.values, color="#d35400", linewidth=1)
        ax7.set_title("Broad USD Index", fontweight="bold", fontsize=10)
        ax7.grid(True, alpha=0.3)

    # --- Panel 6: Equity ---
    ax8 = fig.add_subplot(gs[2, 2])
    if "SPX_DRAWDOWN" in df:
        s = df["SPX_DRAWDOWN"].dropna()
        ax8.fill_between(s.index, 0, s.values, color="#e74c3c", alpha=0.4)
        ax8.set_title("S&P 500 Drawdown (%)", fontweight="bold", fontsize=10)
        ax8.grid(True, alpha=0.3)

    # --- Panel 7: Commodities ---
    ax9 = fig.add_subplot(gs[2, 3])
    if "COPPER_GOLD" in df:
        s = df["COPPER_GOLD"].dropna()
        ax9.plot(s.index, s.values, color="#e67e22", linewidth=1)
        cu_gold_mean = s.rolling(252).mean()
        ax9.plot(cu_gold_mean.index, cu_gold_mean.values, color="gray", linewidth=0.8, linestyle="--", label="1Y MA")
        ax9.set_title("Copper / Gold Ratio (Growth Proxy)", fontweight="bold", fontsize=10)
        ax9.legend(fontsize=7)
        ax9.grid(True, alpha=0.3)

    # --- Panel 8: Merton Dislocation ---
    merton = None
    for m in modules:
        if m["name"] == "MERTON DISLOCATION":
            merton = m
            break

    ax10 = fig.add_subplot(gs[3, :2])
    if merton and "actual_OAS" in merton["details"]:
        ax10.text(
            0.5, 0.7,
            f"Merton Equity-Credit Dislocation Model",
            transform=ax10.transAxes, ha="center", fontsize=12, fontweight="bold",
        )
        info_text = "\n".join([f"  {k}: {v}" for k, v in merton["details"].items()])
        ax10.text(
            0.5, 0.3,
            info_text,
            transform=ax10.transAxes, ha="center", fontsize=9, family="monospace",
            va="center",
        )
        d_color = "#2ecc71" if merton["dislocation"] > 0 else "#e74c3c" if merton["dislocation"] < 0 else "#95a5a6"
        ax10.patch.set_facecolor(d_color)
        ax10.patch.set_alpha(0.1)
    ax10.axis("off")
    ax10.set_title("Merton Dislocation Model", fontweight="bold", fontsize=10)

    # --- Panel 9: Backtest Signal vs Forward Spread Change ---
    ax11 = fig.add_subplot(gs[3, 2:])
    if len(backtest) > 0:
        # Bin signal into quintiles and show average forward spread change
        bt = backtest.dropna().copy()
        bt["signal_bin"] = pd.qcut(bt["signal"], 5, labels=["Very Short", "Short", "Neutral", "Long", "Very Long"], duplicates="drop")
        if "signal_bin" in bt.columns:
            avg_by_bin = bt.groupby("signal_bin", observed=True)["fwd_spread_chg"].mean()
            colors_bt = ["#e74c3c", "#f39c12", "#95a5a6", "#27ae60", "#2ecc71"][:len(avg_by_bin)]
            ax11.bar(range(len(avg_by_bin)), avg_by_bin.values, color=colors_bt, edgecolor="white")
            ax11.set_xticks(range(len(avg_by_bin)))
            ax11.set_xticklabels(avg_by_bin.index, fontsize=8, rotation=15)
            ax11.set_ylabel("Avg 63-day Spread Change (bps)")
            ax11.set_title("Backtest: Signal Quintile vs Forward Spread Change", fontweight="bold", fontsize=10)
            ax11.axhline(0, color="black", linewidth=0.8)
            ax11.grid(True, alpha=0.3)

            # Add annotation
            ax11.text(
                0.02, 0.95,
                "Negative bars on 'Long' = signal correctly\npredicts spread tightening",
                transform=ax11.transAxes, fontsize=7, va="top", style="italic",
            )

    plt.savefig("cross_asset_credit_signals.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: cross_asset_credit_signals.png")
    plt.close()


# =============================================================================
# CONSOLE OUTPUT
# =============================================================================


def print_report(modules: List[Dict], composite: Dict):
    """Print full signal report to console."""
    print("\n" + "=" * 90)
    print("  CROSS-ASSET CREDIT SIGNAL FRAMEWORK - REPORT")
    print("=" * 90)

    comp = composite["composite"]
    color_tag = "BULLISH" if comp > 0.5 else "BEARISH" if comp < -0.5 else "NEUTRAL"
    print(f"\n  COMPOSITE SIGNAL: {comp:+.3f}  [{color_tag}]")
    print(f"  POSITIONING: {composite['position']}")

    print("\n" + "-" * 90)
    print(f"  {'MODULE':<20s} {'SIGNAL':>8s} {'WEIGHT':>8s} {'WEIGHTED':>10s} | {'SUB-SIGNALS'}")
    print("-" * 90)

    for m in modules:
        name = m["name"]
        sig = m.get("signal", 0)
        w = m.get("weight", 1.0)
        ws = sig * w

        # Signal bar
        bar_len = int(abs(sig) * 5)
        bar = ("+" * bar_len if sig > 0 else "-" * bar_len).ljust(10)

        sub = ", ".join(f"{k}={v}" for k, v in m.get("sub_signals", {}).items())
        print(f"  {name:<20s} {sig:>+8.2f} {w:>8.1f} {ws:>+10.2f} | {sub}")

        # Print details
        for dk, dv in m.get("details", {}).items():
            print(f"  {'':20s} {'':8s} {'':8s} {'':10s} | {dk}: {dv}")
        print()

    print("-" * 90)

    # iTraxx positioning
    print("\n  iTRAXX POSITIONING GUIDANCE:")
    print("  " + "-" * 55)
    if comp > 0.5:
        print("  iTraxx Main:       SELL PROTECTION")
        print("  iTraxx Crossover:  SELL PROTECTION (overweight)")
        print("  Xover/Main:        Overweight Xover for carry")
        print("  Conviction:        HIGH" if comp > 1.0 else "  Conviction:        MEDIUM")
    elif comp > 0.15:
        print("  iTraxx Main:       SELL PROTECTION (small)")
        print("  iTraxx Crossover:  SELL PROTECTION (equal weight)")
        print("  Xover/Main:        Neutral tilt")
        print("  Conviction:        LOW-MEDIUM")
    elif comp > -0.15:
        print("  iTraxx Main:       FLAT")
        print("  iTraxx Crossover:  FLAT (carry only)")
        print("  Xover/Main:        Neutral")
        print("  Conviction:        LOW (no directional edge)")
    elif comp > -0.5:
        print("  iTraxx Main:       FLAT / small BUY PROTECTION")
        print("  iTraxx Crossover:  BUY PROTECTION (underweight)")
        print("  Xover/Main:        Underweight Xover")
        print("  Conviction:        LOW-MEDIUM")
    else:
        print("  iTraxx Main:       BUY PROTECTION")
        print("  iTraxx Crossover:  BUY PROTECTION (max underweight)")
        print("  Xover/Main:        Heavy underweight Xover")
        print("  Conviction:        HIGH" if comp < -1.0 else "  Conviction:        MEDIUM")

    # Cross-asset risk flags
    print("\n  RISK FLAGS:")
    for m in modules:
        sig = m.get("signal", 0)
        if abs(sig) >= 1.5:
            direction = "BULLISH" if sig > 0 else "BEARISH"
            print(f"  !! {m['name']} at extreme ({sig:+.2f}) - {direction} OUTLIER")

    print("\n" + "=" * 90)


# =============================================================================
# MAIN
# =============================================================================


def main():
    print("\n" + "=" * 70)
    print("  CROSS-ASSET CREDIT SIGNAL FRAMEWORK")
    print("  Focus: iTraxx Main & Crossover")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  History: {HISTORY_YEARS} years | Z-Score Window: {ZSCORE_WINDOW} days")
    print()

    # 1. Fetch data
    df = fetch_data()

    # 2. Compute derived series
    print("\n  Computing derived series...")
    df = compute_derived(df)

    # 3. Run signal modules
    print("  Running signal modules...")
    mod_vol = signal_equity_vol(df)
    mod_rates = signal_rates(df)
    mod_fx = signal_fx(df)
    mod_equity = signal_equity(df)
    mod_commodities = signal_commodities(df)
    mod_merton = merton_dislocation(df)

    modules = [mod_vol, mod_rates, mod_fx, mod_equity, mod_commodities, mod_merton]

    # 4. Composite
    print("  Computing composite signal...")
    composite = compute_composite(modules)

    # 5. Backtest
    print("  Running historical backtest...")
    backtest = backtest_composite_signal(df, lookback_days=63)

    # 6. Report
    print_report(modules, composite)

    # 7. Visualization
    print("\n  Generating dashboard chart...")
    plot_dashboard(df, modules, composite, backtest)

    # 8. Save signal history
    if len(backtest) > 0:
        backtest.tail(252).to_csv("cross_asset_signal_history.csv")
        print(f"  Signal history saved: cross_asset_signal_history.csv")

    # Backtest stats
    if len(backtest) > 100:
        bt = backtest.dropna()
        corr = bt["signal"].corr(bt["fwd_spread_chg"])
        # Negative correlation is GOOD (positive signal predicts spread tightening)
        print(f"\n  BACKTEST STATS:")
        print(f"  Signal vs 63-day spread change correlation: {corr:.3f}")
        print(f"  (Negative = good: positive signal correctly predicts tightening)")

        # Hit rate: when signal > 0, does spread tighten?
        long_signals = bt[bt["signal"] > 0.3]
        short_signals = bt[bt["signal"] < -0.3]
        if len(long_signals) > 10:
            hit_long = (long_signals["fwd_spread_chg"] < 0).mean() * 100
            print(f"  Long signal hit rate (spreads tightened): {hit_long:.0f}% (n={len(long_signals)})")
        if len(short_signals) > 10:
            hit_short = (short_signals["fwd_spread_chg"] > 0).mean() * 100
            print(f"  Short signal hit rate (spreads widened):  {hit_short:.0f}% (n={len(short_signals)})")

    print("\n  DONE.\n")


if __name__ == "__main__":
    main()
