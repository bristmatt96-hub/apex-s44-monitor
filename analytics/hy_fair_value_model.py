#!/usr/bin/env python3
"""
High-Yield Fair Value & Z-Score Model
=======================================
Spread decomposition, rich/cheap scoring, and quality rotation signals
for US & European High Yield credit.

Components:
  1. SPREAD DECOMPOSITION  - Break OAS into expected default loss, liquidity premium, risk premium
  2. Z-SCORE MODEL         - Rolling Z-scores & percentiles by rating (BB/B/CCC) and maturity
  3. FAIR VALUE REGRESSION  - Macro-based fair value for HY spreads (VIX, curve, profits, leverage)
  4. QUALITY ROTATION       - Signal for when to move up/down in quality within HY
  5. RICH/CHEAP SCORECARD   - Summary of all valuation signals with positioning guidance

Usage:
  pip install fredapi pandas matplotlib numpy scipy
  set FRED_API_KEY=your_key_here
  python hy_fair_value_model.py
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_YEARS = 12
START_DATE = datetime.now() - timedelta(days=365 * HISTORY_YEARS)
ZSCORE_WINDOW_DAYS = 252 * 5    # 5-year rolling window for daily Z-scores
ZSCORE_WINDOW_SHORT = 252 * 2   # 2-year for shorter-term signal
REGRESSION_WINDOW = 252 * 3     # 3-year rolling regression for fair value


# =============================================================================
# FRED SERIES REGISTRY
# =============================================================================

SPREAD_SERIES = {
    # --- US HY by Rating ---
    "US_HY":       {"id": "BAMLH0A0HYM2",     "desc": "US HY Total OAS",           "universe": "US_HY", "rating": "HY"},
    "US_BB":       {"id": "BAMLH0A1HYBB",      "desc": "US BB OAS",                 "universe": "US_HY", "rating": "BB"},
    "US_B":        {"id": "BAMLH0A2HYB",       "desc": "US B OAS",                  "universe": "US_HY", "rating": "B"},
    "US_CCC":      {"id": "BAMLH0A3HYC",       "desc": "US CCC & Lower OAS",        "universe": "US_HY", "rating": "CCC"},

    # --- US HY Effective Yields ---
    "US_HY_YLD":   {"id": "BAMLH0A0HYM2EY",    "desc": "US HY Total Yield",         "universe": "US_HY", "rating": "HY"},
    "US_BB_YLD":   {"id": "BAMLH0A1HYBBEY",     "desc": "US BB Yield",               "universe": "US_HY", "rating": "BB"},
    "US_B_YLD":    {"id": "BAMLH0A2HYBEY",      "desc": "US B Yield",                "universe": "US_HY", "rating": "B"},
    "US_CCC_YLD":  {"id": "BAMLH0A3HYCEY",      "desc": "US CCC Yield",              "universe": "US_HY", "rating": "CCC"},

    # --- US IG by Rating ---
    "US_IG":       {"id": "BAMLC0A0CM",         "desc": "US IG Total OAS",           "universe": "US_IG", "rating": "IG"},
    "US_AAA":      {"id": "BAMLC0A1CAAA",       "desc": "US AAA OAS",                "universe": "US_IG", "rating": "AAA"},
    "US_AA":       {"id": "BAMLC0A2CAA",        "desc": "US AA OAS",                 "universe": "US_IG", "rating": "AA"},
    "US_A":        {"id": "BAMLC0A3CA",         "desc": "US A OAS",                  "universe": "US_IG", "rating": "A"},
    "US_BBB":      {"id": "BAMLC0A4CBBB",       "desc": "US BBB OAS",                "universe": "US_IG", "rating": "BBB"},

    # --- Euro HY ---
    "EUR_HY":      {"id": "BAMLHE00EHYIOAS",    "desc": "Euro HY Total OAS",         "universe": "EUR_HY", "rating": "HY"},
    "EUR_HY_YLD":  {"id": "BAMLHE00EHYIEY",     "desc": "Euro HY Total Yield",       "universe": "EUR_HY", "rating": "HY"},

    # --- US Corporate by Maturity ---
    "US_1_3Y":     {"id": "BAMLC1A0C13Y",       "desc": "US Corp 1-3Y OAS",          "universe": "US_MAT", "rating": "IG"},
    "US_3_5Y":     {"id": "BAMLC2A0C35Y",       "desc": "US Corp 3-5Y OAS",          "universe": "US_MAT", "rating": "IG"},
    "US_5_7Y":     {"id": "BAMLC3A0C57Y",       "desc": "US Corp 5-7Y OAS",          "universe": "US_MAT", "rating": "IG"},
    "US_7_10Y":    {"id": "BAMLC4A0C710Y",      "desc": "US Corp 7-10Y OAS",         "universe": "US_MAT", "rating": "IG"},
    "US_10_15Y":   {"id": "BAMLC7A0C1015Y",     "desc": "US Corp 10-15Y OAS",        "universe": "US_MAT", "rating": "IG"},
    "US_15Y_PLUS": {"id": "BAMLC8A0C15PY",      "desc": "US Corp 15+Y OAS",          "universe": "US_MAT", "rating": "IG"},

    # --- EM HY ---
    "EM_HY":       {"id": "BAMLEMHBHYCRPIOAS",  "desc": "EM HY Corporate OAS",       "universe": "EM", "rating": "HY"},
    "EM_BBB":      {"id": "BAMLEM2BRRBBBCRPIOAS","desc": "EM BBB Corporate OAS",      "universe": "EM", "rating": "BBB"},
}

FUNDAMENTAL_SERIES = {
    # --- Moody's ---
    "MOODY_BAA":   {"id": "BAA",               "desc": "Moody's Baa Yield"},
    "MOODY_AAA":   {"id": "AAA",               "desc": "Moody's Aaa Yield"},
    "BAA_10Y":     {"id": "BAA10Y",            "desc": "Baa Yield minus 10Y Treasury"},

    # --- Macro ---
    "VIX":         {"id": "VIXCLS",            "desc": "VIX"},
    "UST_2Y":      {"id": "DGS2",             "desc": "US 2Y Treasury"},
    "UST_10Y":     {"id": "DGS10",            "desc": "US 10Y Treasury"},
    "TIPS_5Y":     {"id": "DFII5",            "desc": "US 5Y TIPS Real Yield"},
    "SPX":         {"id": "SP500",            "desc": "S&P 500"},

    # --- Corporate Fundamentals (quarterly) ---
    "CORP_PROFITS": {"id": "CP",              "desc": "Corporate Profits After Tax"},
    "NFC_DEBT":     {"id": "BCNSDODNS",       "desc": "Nonfinancial Corporate Debt"},
}

# Historical default rates by rating (Moody's long-run average, annual %)
# Source: Moody's Annual Default Study
HISTORICAL_DEFAULT_RATES = {
    "AAA": 0.00, "AA": 0.02, "A": 0.07, "BBB": 0.18,
    "BB": 0.93, "B": 3.44, "CCC": 14.08, "HY": 3.30, "IG": 0.08,
}

# Historical recovery rates by seniority (% of par)
RECOVERY_RATES = {
    "senior_secured": 0.52, "senior_unsecured": 0.37,
    "subordinated": 0.24, "default": 0.40,
}


# =============================================================================
# DATA FETCHING
# =============================================================================


def fetch_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch spread and fundamental data from FRED."""
    from fredapi import Fred

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("ERROR: Set FRED_API_KEY environment variable.")
        print("  Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")
        sys.exit(1)

    fred = Fred(api_key=api_key)

    print("=" * 70)
    print("  FETCHING SPREAD & FUNDAMENTAL DATA FROM FRED")
    print("=" * 70)

    # Fetch spreads
    spread_frames = {}
    print("\n  --- Credit Spreads ---")
    for key, meta in SPREAD_SERIES.items():
        try:
            s = fred.get_series(meta["id"], observation_start=START_DATE)
            spread_frames[key] = s
            n = len(s.dropna())
            latest = s.dropna().iloc[-1] if n > 0 else "N/A"
            dt = s.dropna().index[-1].strftime("%Y-%m-%d") if n > 0 else "N/A"
            print(f"  [OK]   {meta['desc']:30s} | {dt} = {latest}")
        except Exception as e:
            print(f"  [FAIL] {meta['desc']:30s} | {e}")

    # Fetch fundamentals
    fund_frames = {}
    print("\n  --- Fundamentals ---")
    for key, meta in FUNDAMENTAL_SERIES.items():
        try:
            s = fred.get_series(meta["id"], observation_start=START_DATE)
            fund_frames[key] = s
            n = len(s.dropna())
            latest = s.dropna().iloc[-1] if n > 0 else "N/A"
            dt = s.dropna().index[-1].strftime("%Y-%m-%d") if n > 0 else "N/A"
            print(f"  [OK]   {meta['desc']:30s} | {dt} = {latest}")
        except Exception as e:
            print(f"  [FAIL] {meta['desc']:30s} | {e}")

    spreads = pd.DataFrame(spread_frames)
    spreads.index = pd.to_datetime(spreads.index)
    spreads = spreads.resample("B").last().ffill(limit=10)
    funds = pd.DataFrame(fund_frames)
    funds.index = pd.to_datetime(funds.index)
    funds = funds.resample("B").last().ffill(limit=30)

    return spreads, funds


# =============================================================================
# 1. SPREAD DECOMPOSITION
# =============================================================================


def decompose_spread(oas: float, rating: str, recovery: float = None) -> Dict:
    """
    Decompose OAS into three components:

    OAS = Expected Default Loss + Liquidity Premium + Risk Premium (excess compensation)

    Expected Default Loss = Default Rate x (1 - Recovery Rate) x 10000 (to bps)
    Liquidity Premium = estimated at 30-80bps depending on rating
    Risk Premium = OAS - Default Loss - Liquidity Premium

    The risk premium is the "excess" compensation above fair default-adjusted value.
    Positive risk premium = you're getting paid more than default risk warrants.
    """
    if recovery is None:
        recovery = RECOVERY_RATES["default"]

    default_rate = HISTORICAL_DEFAULT_RATES.get(rating, 3.0) / 100.0
    expected_loss_bps = default_rate * (1 - recovery) * 10000

    # Liquidity premium estimates by rating bucket
    liquidity_estimates = {
        "AAA": 15, "AA": 20, "A": 25, "BBB": 35,
        "BB": 50, "B": 70, "CCC": 120, "HY": 60, "IG": 25,
    }
    liquidity_bps = liquidity_estimates.get(rating, 50)

    risk_premium_bps = oas - expected_loss_bps - liquidity_bps

    return {
        "OAS_total": round(oas, 0),
        "expected_default_loss": round(expected_loss_bps, 1),
        "liquidity_premium": round(liquidity_bps, 0),
        "risk_premium": round(risk_premium_bps, 1),
        "risk_premium_pct": round(risk_premium_bps / oas * 100, 1) if oas > 0 else 0,
        "default_rate_assumed": round(default_rate * 100, 2),
        "recovery_assumed": round(recovery * 100, 0),
    }


def spread_decomposition_table(spreads: pd.DataFrame) -> pd.DataFrame:
    """Build decomposition table for all available rating buckets."""
    rows = []
    decomp_keys = [
        ("US_HY",  "HY"),  ("US_BB",  "BB"),  ("US_B",   "B"),  ("US_CCC", "CCC"),
        ("US_IG",  "IG"),  ("US_BBB", "BBB"), ("US_A",   "A"),  ("US_AA",  "AA"),
        ("US_AAA", "AAA"), ("EUR_HY", "HY"),
    ]

    for key, rating in decomp_keys:
        if key not in spreads.columns:
            continue
        oas = spreads[key].dropna().iloc[-1] if len(spreads[key].dropna()) > 0 else np.nan
        if pd.isna(oas):
            continue

        decomp = decompose_spread(oas, rating)
        label = SPREAD_SERIES[key]["desc"] if key in SPREAD_SERIES else key
        rows.append({"Index": label, "Rating": rating, **decomp})

    return pd.DataFrame(rows)


# =============================================================================
# 2. Z-SCORE MODEL BY RATING BUCKET
# =============================================================================


def compute_spread_zscores(spreads: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling Z-scores and percentiles for each spread series.
    Uses 5-year rolling window for long-term context, 2-year for short-term.
    """
    results = []
    oas_keys = [k for k, v in SPREAD_SERIES.items() if "YLD" not in k and "TRIV" not in k]

    for key in oas_keys:
        if key not in spreads.columns:
            continue

        s = spreads[key].dropna()
        if len(s) < 252:
            continue

        current = s.iloc[-1]

        # 5-year Z-score
        mean_5y = s.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).mean()
        std_5y = s.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).std()
        z_5y = ((s - mean_5y) / std_5y.replace(0, np.nan)).iloc[-1]

        # 2-year Z-score
        mean_2y = s.rolling(ZSCORE_WINDOW_SHORT, min_periods=126).mean()
        std_2y = s.rolling(ZSCORE_WINDOW_SHORT, min_periods=126).std()
        z_2y = ((s - mean_2y) / std_2y.replace(0, np.nan)).iloc[-1]

        # Percentile ranks
        pct_5y = sp_stats.percentileofscore(s.tail(ZSCORE_WINDOW_DAYS).dropna(), current)
        pct_2y = sp_stats.percentileofscore(s.tail(ZSCORE_WINDOW_SHORT).dropna(), current)
        pct_full = sp_stats.percentileofscore(s, current)

        # Historical range
        high_5y = s.tail(ZSCORE_WINDOW_DAYS).max()
        low_5y = s.tail(ZSCORE_WINDOW_DAYS).min()
        mean_val = s.tail(ZSCORE_WINDOW_DAYS).mean()

        # Where in the range (0 = at low, 100 = at high)
        range_position = (current - low_5y) / (high_5y - low_5y) * 100 if high_5y != low_5y else 50

        # Rich/Cheap signal
        if z_5y < -1.5:
            valuation = "VERY TIGHT (rich)"
        elif z_5y < -0.5:
            valuation = "TIGHT (modestly rich)"
        elif z_5y < 0.5:
            valuation = "FAIR VALUE"
        elif z_5y < 1.5:
            valuation = "WIDE (modestly cheap)"
        else:
            valuation = "VERY WIDE (cheap)"

        meta = SPREAD_SERIES.get(key, {})
        results.append({
            "Index": meta.get("desc", key),
            "Universe": meta.get("universe", ""),
            "Rating": meta.get("rating", ""),
            "Current": round(current, 0),
            "5Y_Mean": round(mean_val, 0),
            "5Y_High": round(high_5y, 0),
            "5Y_Low": round(low_5y, 0),
            "Range_%": round(range_position, 0),
            "Z_5Y": round(z_5y, 2),
            "Z_2Y": round(z_2y, 2),
            "Pct_5Y": round(pct_5y, 0),
            "Pct_2Y": round(pct_2y, 0),
            "Pct_Full": round(pct_full, 0),
            "Valuation": valuation,
        })

    return pd.DataFrame(results)


# =============================================================================
# 3. FUNDAMENTAL FAIR VALUE MODEL
# =============================================================================


def fair_value_regression(spreads: pd.DataFrame, funds: pd.DataFrame) -> Dict:
    """
    Macro-based fair value model for US HY spreads.

    Model: US_HY_OAS = f(VIX, 2s10s_slope, Real_Rates, Equity_Momentum, Baa_spread)

    Uses rolling 3-year OLS to get time-varying coefficients.
    Returns fair value, residual (rich/cheap), and model stats.
    """
    result = {"name": "FUNDAMENTAL FAIR VALUE", "details": {}}

    required_spreads = ["US_HY"]
    required_funds = ["VIX", "UST_2Y", "UST_10Y", "TIPS_5Y", "SPX", "BAA_10Y"]

    if not all(k in spreads.columns for k in required_spreads):
        result["details"]["status"] = "Missing US HY spread"
        return result
    if not all(k in funds.columns for k in required_funds):
        missing = [k for k in required_funds if k not in funds.columns]
        result["details"]["status"] = f"Missing fundamentals: {missing}"
        return result

    # Build model DataFrame
    model = pd.DataFrame(index=spreads.index)
    model["y"] = spreads["US_HY"]
    model["VIX"] = funds["VIX"]
    model["slope_2s10s"] = funds["UST_10Y"] - funds["UST_2Y"]
    model["real_rate_5Y"] = funds["TIPS_5Y"]
    model["spx_mom_63d"] = funds["SPX"].pct_change(63) * 100
    model["baa_spread"] = funds["BAA_10Y"]

    model = model.dropna()
    if len(model) < REGRESSION_WINDOW:
        result["details"]["status"] = f"Insufficient data ({len(model)})"
        return result

    # Rolling regression (last 3 years)
    train = model.iloc[-REGRESSION_WINDOW:]
    Y = train["y"].values
    X_cols = ["VIX", "slope_2s10s", "real_rate_5Y", "spx_mom_63d", "baa_spread"]
    X = np.column_stack([np.ones(len(train))] + [train[c].values for c in X_cols])

    try:
        beta, residuals_sum, rank, sv = np.linalg.lstsq(X, Y, rcond=None)
    except Exception:
        result["details"]["status"] = "Regression failed"
        return result

    # Fair value at current inputs
    current_x = np.array([1.0] + [model[c].iloc[-1] for c in X_cols])
    fair_value = float(np.dot(beta, current_x))
    actual = model["y"].iloc[-1]
    residual = actual - fair_value
    residual_pct = (residual / fair_value) * 100

    # Residual Z-score (vs training period)
    fitted_train = X @ beta
    resid_train = Y - fitted_train
    resid_z = (residual - np.mean(resid_train)) / np.std(resid_train)
    r_squared = 1 - np.var(resid_train) / np.var(Y)

    # Also do for EUR HY (using US model as proxy, adjusting by EUR/US ratio)
    eur_fair = None
    if "EUR_HY" in spreads.columns and "US_HY" in spreads.columns:
        eur = spreads["EUR_HY"].dropna()
        us = spreads["US_HY"].dropna()
        common = eur.index.intersection(us.index)
        if len(common) > 252:
            ratio_mean = (eur.loc[common] / us.loc[common]).tail(ZSCORE_WINDOW_DAYS).mean()
            eur_fair = fair_value * ratio_mean
            eur_actual = eur.iloc[-1]
            eur_resid = eur_actual - eur_fair

    # Coefficients interpretation
    coef_names = ["intercept"] + X_cols
    coef_dict = {name: round(float(b), 3) for name, b in zip(coef_names, beta)}

    result["fair_value_US_HY"] = round(fair_value, 0)
    result["actual_US_HY"] = round(actual, 0)
    result["residual_US_HY"] = round(residual, 0)
    result["residual_pct"] = round(residual_pct, 1)
    result["residual_z"] = round(resid_z, 2)
    result["r_squared"] = round(r_squared, 3)

    if eur_fair is not None:
        result["fair_value_EUR_HY"] = round(eur_fair, 0)
        result["actual_EUR_HY"] = round(eur_actual, 0)
        result["residual_EUR_HY"] = round(eur_resid, 0)

    result["coefficients"] = coef_dict
    result["details"] = {
        "US_HY_actual": f"{actual:.0f}bps",
        "US_HY_fair_value": f"{fair_value:.0f}bps",
        "residual": f"{residual:+.0f}bps ({residual_pct:+.1f}%)",
        "residual_Z": f"{resid_z:+.2f}",
        "R_squared": f"{r_squared:.3f}",
        "interpretation": (
            "HY CHEAP vs fundamentals (spreads wider than macro warrants)"
            if resid_z > 0.75
            else "HY RICH vs fundamentals (spreads tighter than macro warrants)"
            if resid_z < -0.75
            else "HY near FAIR VALUE vs fundamentals"
        ),
    }

    return result


# =============================================================================
# 4. QUALITY ROTATION SIGNAL
# =============================================================================


def quality_rotation_signal(spreads: pd.DataFrame, funds: pd.DataFrame) -> Dict:
    """
    Quality Rotation Model: When to go Up vs Down in Quality within HY.

    Signal uses:
    - BB/CCC spread ratio: high = CCC cheap (go down in quality), low = CCC rich (go up)
    - BB-B spread difference momentum: widening = stress (go up), tightening = opportunity (go down)
    - VIX regime: low vol = safe to go down in quality, high vol = go up
    - Credit curve slope: BB-CCC spread vs history

    Output: Score from -2 (strong up-in-quality) to +2 (strong down-in-quality)
    """
    signals = {}
    details = {}

    # CCC/BB spread ratio
    if "US_CCC" in spreads and "US_BB" in spreads:
        ccc = spreads["US_CCC"].dropna()
        bb = spreads["US_BB"].dropna()
        common = ccc.index.intersection(bb.index)
        if len(common) > 252:
            ratio = ccc.loc[common] / bb.loc[common]
            ratio_current = ratio.iloc[-1]
            ratio_mean = ratio.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).mean()
            ratio_std = ratio.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).std()
            ratio_z = ((ratio - ratio_mean) / ratio_std.replace(0, np.nan)).iloc[-1]

            # High ratio Z = CCC very wide relative to BB = potential opportunity to go down
            if ratio_z > 1.5:
                signals["CCC_BB_ratio"] = 2
            elif ratio_z > 0.5:
                signals["CCC_BB_ratio"] = 1
            elif ratio_z > -0.5:
                signals["CCC_BB_ratio"] = 0
            elif ratio_z > -1.5:
                signals["CCC_BB_ratio"] = -1
            else:
                signals["CCC_BB_ratio"] = -2

            details["CCC/BB"] = f"{ratio_current:.2f}x (Z={ratio_z:+.2f})"

    # B-BB spread momentum (63-day change)
    if "US_B" in spreads and "US_BB" in spreads:
        b_bb = spreads["US_B"] - spreads["US_BB"]
        b_bb_mom = b_bb.diff(63)
        if len(b_bb_mom.dropna()) > 126:
            mom_z_series = (b_bb_mom - b_bb_mom.rolling(504, min_periods=126).mean()) / b_bb_mom.rolling(504, min_periods=126).std().replace(0, np.nan)
            mom_z = mom_z_series.dropna().iloc[-1] if len(mom_z_series.dropna()) > 0 else 0

            # Widening B-BB = stress in lower quality = go up
            if mom_z > 1.0:
                signals["B_BB_momentum"] = -2
            elif mom_z > 0.3:
                signals["B_BB_momentum"] = -1
            elif mom_z > -0.3:
                signals["B_BB_momentum"] = 0
            elif mom_z > -1.0:
                signals["B_BB_momentum"] = 1
            else:
                signals["B_BB_momentum"] = 2

            details["B-BB_3m_chg"] = f"{b_bb_mom.dropna().iloc[-1]:+.0f}bps (Z={mom_z:+.2f})"

    # VIX regime for quality tilt
    if "VIX" in funds:
        vix = funds["VIX"].dropna()
        if len(vix) > 0:
            vix_current = vix.iloc[-1]
            if vix_current > 30:
                signals["VIX_regime"] = -2  # high vol = go up in quality
            elif vix_current > 22:
                signals["VIX_regime"] = -1
            elif vix_current > 16:
                signals["VIX_regime"] = 1   # moderate vol = ok to go down
            else:
                signals["VIX_regime"] = 1   # low vol = go down (but watch for snap)

            details["VIX"] = f"{vix_current:.1f}"

    # HY-IG spread ratio (compression = late cycle, go up)
    if "US_HY" in spreads and "US_IG" in spreads:
        hy_ig = spreads["US_HY"] / spreads["US_IG"]
        if len(hy_ig.dropna()) > 252:
            hy_ig_z_series = (hy_ig - hy_ig.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).mean()) / hy_ig.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).std().replace(0, np.nan)
            hy_ig_z = hy_ig_z_series.dropna().iloc[-1] if len(hy_ig_z_series.dropna()) > 0 else 0

            # Low HY/IG ratio Z = compressed = complacent = go up in quality
            if hy_ig_z < -1.0:
                signals["HY_IG_ratio"] = -1
            elif hy_ig_z > 1.0:
                signals["HY_IG_ratio"] = 1  # wide = opportunity in lower quality
            else:
                signals["HY_IG_ratio"] = 0

            details["HY/IG"] = f"{hy_ig.dropna().iloc[-1]:.2f}x (Z={hy_ig_z:+.2f})"

    # Composite
    if signals:
        weights = {"CCC_BB_ratio": 2.0, "B_BB_momentum": 1.5, "VIX_regime": 1.0, "HY_IG_ratio": 1.0}
        total_w = sum(weights.get(k, 1.0) for k in signals)
        composite = sum(signals[k] * weights.get(k, 1.0) for k in signals) / total_w
    else:
        composite = 0

    # Positioning
    if composite > 1.0:
        position = "STRONG DOWN IN QUALITY: Overweight CCC/B vs BB, sell BB prot / buy CCC prot"
    elif composite > 0.3:
        position = "TILT DOWN IN QUALITY: Modestly overweight B vs BB"
    elif composite > -0.3:
        position = "NEUTRAL QUALITY: Equal-weight across rating buckets"
    elif composite > -1.0:
        position = "TILT UP IN QUALITY: Overweight BB vs B/CCC"
    else:
        position = "STRONG UP IN QUALITY: Avoid CCC, overweight BB, consider IG crossover"

    return {
        "composite": round(composite, 2),
        "position": position,
        "sub_signals": signals,
        "details": details,
    }


# =============================================================================
# 5. RICH/CHEAP SCORECARD
# =============================================================================


def rich_cheap_scorecard(
    zscore_table: pd.DataFrame,
    decomp_table: pd.DataFrame,
    fair_value: Dict,
    quality: Dict,
) -> None:
    """Print the full rich/cheap scorecard."""

    print("\n" + "=" * 100)
    print("  HIGH-YIELD FAIR VALUE & Z-SCORE MODEL")
    print("=" * 100)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # --- Section 1: Spread Z-Scores ---
    print("\n" + "=" * 100)
    print("  1. SPREAD Z-SCORES & PERCENTILES")
    print("=" * 100)

    if len(zscore_table) > 0:
        # Print US HY section
        us_hy = zscore_table[zscore_table["Universe"].isin(["US_HY"])]
        if len(us_hy) > 0:
            print("\n  US HIGH YIELD:")
            print(f"  {'Index':<25s} {'Current':>8s} {'5Y Mean':>8s} {'5Y Low':>8s} {'5Y High':>8s} {'Range%':>7s} {'Z(5Y)':>7s} {'Z(2Y)':>7s} {'Pct(5Y)':>8s} {'Valuation':<25s}")
            print("  " + "-" * 120)
            for _, row in us_hy.iterrows():
                print(f"  {row['Index']:<25s} {row['Current']:>8.0f} {row['5Y_Mean']:>8.0f} {row['5Y_Low']:>8.0f} {row['5Y_High']:>8.0f} {row['Range_%']:>6.0f}% {row['Z_5Y']:>+7.2f} {row['Z_2Y']:>+7.2f} {row['Pct_5Y']:>7.0f}% {row['Valuation']:<25s}")

        # Print US IG section
        us_ig = zscore_table[zscore_table["Universe"].isin(["US_IG"])]
        if len(us_ig) > 0:
            print("\n  US INVESTMENT GRADE:")
            print(f"  {'Index':<25s} {'Current':>8s} {'5Y Mean':>8s} {'5Y Low':>8s} {'5Y High':>8s} {'Range%':>7s} {'Z(5Y)':>7s} {'Z(2Y)':>7s} {'Pct(5Y)':>8s} {'Valuation':<25s}")
            print("  " + "-" * 120)
            for _, row in us_ig.iterrows():
                print(f"  {row['Index']:<25s} {row['Current']:>8.0f} {row['5Y_Mean']:>8.0f} {row['5Y_Low']:>8.0f} {row['5Y_High']:>8.0f} {row['Range_%']:>6.0f}% {row['Z_5Y']:>+7.2f} {row['Z_2Y']:>+7.2f} {row['Pct_5Y']:>7.0f}% {row['Valuation']:<25s}")

        # Print EUR HY
        eur = zscore_table[zscore_table["Universe"].isin(["EUR_HY"])]
        if len(eur) > 0:
            print("\n  EURO HIGH YIELD:")
            print(f"  {'Index':<25s} {'Current':>8s} {'5Y Mean':>8s} {'5Y Low':>8s} {'5Y High':>8s} {'Range%':>7s} {'Z(5Y)':>7s} {'Z(2Y)':>7s} {'Pct(5Y)':>8s} {'Valuation':<25s}")
            print("  " + "-" * 120)
            for _, row in eur.iterrows():
                print(f"  {row['Index']:<25s} {row['Current']:>8.0f} {row['5Y_Mean']:>8.0f} {row['5Y_Low']:>8.0f} {row['5Y_High']:>8.0f} {row['Range_%']:>6.0f}% {row['Z_5Y']:>+7.2f} {row['Z_2Y']:>+7.2f} {row['Pct_5Y']:>7.0f}% {row['Valuation']:<25s}")

        # Print maturity
        mat = zscore_table[zscore_table["Universe"].isin(["US_MAT"])]
        if len(mat) > 0:
            print("\n  US CORPORATE BY MATURITY:")
            print(f"  {'Index':<25s} {'Current':>8s} {'5Y Mean':>8s} {'Z(5Y)':>7s} {'Pct(5Y)':>8s} {'Valuation':<25s}")
            print("  " + "-" * 80)
            for _, row in mat.iterrows():
                print(f"  {row['Index']:<25s} {row['Current']:>8.0f} {row['5Y_Mean']:>8.0f} {row['Z_5Y']:>+7.2f} {row['Pct_5Y']:>7.0f}% {row['Valuation']:<25s}")

    # --- Section 2: Spread Decomposition ---
    print("\n" + "=" * 100)
    print("  2. SPREAD DECOMPOSITION (Expected Loss + Liquidity + Risk Premium)")
    print("=" * 100)

    if len(decomp_table) > 0:
        print(f"\n  {'Index':<25s} {'OAS':>7s} {'Dflt Loss':>10s} {'Liq Prem':>10s} {'Risk Prem':>10s} {'Risk%':>7s} {'Dflt Rate':>10s} {'Recovery':>10s}")
        print("  " + "-" * 100)
        for _, row in decomp_table.iterrows():
            rp_color = "***" if row["risk_premium"] > 200 else "**" if row["risk_premium"] > 100 else "*" if row["risk_premium"] > 50 else ""
            print(
                f"  {row['Index']:<25s} {row['OAS_total']:>7.0f} {row['expected_default_loss']:>10.1f} "
                f"{row['liquidity_premium']:>10.0f} {row['risk_premium']:>10.1f}{rp_color:3s} "
                f"{row['risk_premium_pct']:>6.1f}% {row['default_rate_assumed']:>9.2f}% {row['recovery_assumed']:>9.0f}%"
            )
        print("\n  * = modest excess compensation  ** = significant  *** = very attractive risk premium")
        print("  Default rates: Moody's long-run averages | Recovery: 40% (senior unsecured blend)")

    # --- Section 3: Fair Value Model ---
    print("\n" + "=" * 100)
    print("  3. FUNDAMENTAL FAIR VALUE MODEL")
    print("=" * 100)

    if "fair_value_US_HY" in fair_value:
        fv = fair_value
        print(f"\n  Model: US HY OAS = f(VIX, 2s10s, Real Rates, SPX Momentum, Baa Spread)")
        print(f"  Window: {REGRESSION_WINDOW // 252}Y rolling OLS | R-squared: {fv['r_squared']:.3f}")
        print()
        print(f"  US HY Actual:     {fv['actual_US_HY']:>6.0f} bps")
        print(f"  US HY Fair Value: {fv['fair_value_US_HY']:>6.0f} bps")
        print(f"  Residual:         {fv['residual_US_HY']:>+6.0f} bps ({fv['residual_pct']:>+.1f}%)")
        print(f"  Residual Z-Score: {fv['residual_z']:>+6.2f}")
        print(f"  >>> {fv['details']['interpretation']} <<<")

        if "fair_value_EUR_HY" in fv:
            print(f"\n  EUR HY Actual:     {fv['actual_EUR_HY']:>6.0f} bps")
            print(f"  EUR HY Fair Value: {fv['fair_value_EUR_HY']:>6.0f} bps  (scaled from US model)")
            print(f"  Residual:          {fv['residual_EUR_HY']:>+6.0f} bps")

        if "coefficients" in fv:
            print(f"\n  Model Coefficients:")
            for k, v in fv["coefficients"].items():
                print(f"    {k:20s}: {v:+.3f}")
    else:
        print(f"\n  {fair_value.get('details', {}).get('status', 'Model not available')}")

    # --- Section 4: Quality Rotation ---
    print("\n" + "=" * 100)
    print("  4. QUALITY ROTATION SIGNAL (Up/Down in Quality within HY)")
    print("=" * 100)

    q = quality
    print(f"\n  Composite Score: {q['composite']:+.2f}")
    print(f"  >>> {q['position']} <<<")
    print()
    for k, v in q["sub_signals"].items():
        direction = "DOWN in quality" if v > 0 else "UP in quality" if v < 0 else "NEUTRAL"
        print(f"    {k:20s}: {v:>+3d}  ({direction})")
    print()
    for k, v in q["details"].items():
        print(f"    {k}: {v}")

    # --- Section 5: Summary ---
    print("\n" + "=" * 100)
    print("  5. POSITIONING SUMMARY")
    print("=" * 100)

    # Overall valuation
    if len(zscore_table) > 0:
        us_hy_row = zscore_table[zscore_table["Index"].str.contains("US HY Total")]
        eur_hy_row = zscore_table[zscore_table["Index"].str.contains("Euro HY Total")]

        if len(us_hy_row) > 0:
            r = us_hy_row.iloc[0]
            print(f"\n  US HY:  {r['Current']:.0f}bps | Z={r['Z_5Y']:+.2f} | {r['Pct_5Y']:.0f}th pctile | {r['Valuation']}")

        if len(eur_hy_row) > 0:
            r = eur_hy_row.iloc[0]
            print(f"  EUR HY: {r['Current']:.0f}bps | Z={r['Z_5Y']:+.2f} | {r['Pct_5Y']:.0f}th pctile | {r['Valuation']}")

    if "fair_value_US_HY" in fair_value:
        fv = fair_value
        print(f"\n  Fair Value Model: Spreads are {fv['residual_US_HY']:+.0f}bps from fundamental fair value (Z={fv['residual_z']:+.2f})")

    print(f"  Quality Rotation: {q['position']}")

    print("\n  iTRAXX IMPLICATIONS:")
    # Combine Z-score + fair value + quality signals
    us_hy_z = 0
    if len(zscore_table) > 0:
        us_hy_rows = zscore_table[zscore_table["Index"].str.contains("US HY Total")]
        if len(us_hy_rows) > 0:
            us_hy_z = us_hy_rows.iloc[0]["Z_5Y"]

    fv_z = fair_value.get("residual_z", 0)
    q_score = quality["composite"]

    # Combined view
    val_score = (us_hy_z + fv_z) / 2  # positive = wide/cheap
    if val_score > 0.75 and q_score > 0:
        print("  -> SELL PROTECTION on both Main and Xover")
        print("  -> Overweight Crossover (cheap + quality signal says go down)")
        print("  -> Consider single-name longs in dislocated B/CCC names")
    elif val_score > 0.75 and q_score < 0:
        print("  -> SELL PROTECTION, but favor Main over Crossover")
        print("  -> Go up in quality within HY longs")
        print("  -> BB names preferred over B/CCC")
    elif val_score < -0.75:
        print("  -> CAUTION: Spreads look rich vs history and fundamentals")
        print("  -> Reduce outright longs, consider buying protection on Xover")
        print("  -> Tighten stop-losses on existing credit longs")
    else:
        print("  -> NEUTRAL: Spreads near fair value")
        print("  -> Focus on carry and relative value rather than directional")
        print(f"  -> Quality tilt: {q['position']}")

    print("\n" + "=" * 100)


# =============================================================================
# VISUALIZATION
# =============================================================================


def plot_dashboard(spreads: pd.DataFrame, zscore_table: pd.DataFrame, fair_value: Dict, quality: Dict):
    """Full HY fair value dashboard visualization."""
    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "HIGH-YIELD FAIR VALUE & Z-SCORE DASHBOARD",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Data: FRED/ICE BofA",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(4, 4, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # --- Panel 1: US HY Spreads by Rating ---
    ax1 = fig.add_subplot(gs[0, :2])
    for key, color, label in [
        ("US_HY", "black", "US HY Total"),
        ("US_BB", "#3498db", "BB"),
        ("US_B", "#e67e22", "B"),
        ("US_CCC", "#e74c3c", "CCC"),
    ]:
        if key in spreads:
            s = spreads[key].dropna()
            ax1.plot(s.index, s.values, color=color, linewidth=1.0 if key != "US_HY" else 1.5, label=label)
    ax1.set_title("US HY OAS by Rating Bucket", fontweight="bold")
    ax1.set_ylabel("OAS (bps)")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale("log")

    # --- Panel 2: EUR HY vs US HY ---
    ax2 = fig.add_subplot(gs[0, 2:])
    if "EUR_HY" in spreads and "US_HY" in spreads:
        for key, color, label in [("US_HY", "#2c3e50", "US HY"), ("EUR_HY", "#e74c3c", "Euro HY")]:
            s = spreads[key].dropna()
            ax2.plot(s.index, s.values, color=color, linewidth=1.2, label=label)
    ax2.set_title("US HY vs Euro HY OAS", fontweight="bold")
    ax2.set_ylabel("OAS (bps)")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # --- Panel 3: Z-Score Bar Chart ---
    ax3 = fig.add_subplot(gs[1, :2])
    if len(zscore_table) > 0:
        hy_ig = zscore_table[zscore_table["Universe"].isin(["US_HY", "US_IG", "EUR_HY"])]
        if len(hy_ig) > 0:
            hy_ig_sorted = hy_ig.sort_values("Z_5Y")
            colors = ["#e74c3c" if z < -1 else "#f39c12" if z < 0 else "#2ecc71" if z < 1 else "#27ae60" for z in hy_ig_sorted["Z_5Y"]]
            ax3.barh(range(len(hy_ig_sorted)), hy_ig_sorted["Z_5Y"].values, color=colors, edgecolor="white")
            ax3.set_yticks(range(len(hy_ig_sorted)))
            ax3.set_yticklabels(hy_ig_sorted["Index"].values, fontsize=8)
            ax3.axvline(0, color="black", linewidth=0.8)
            ax3.axvline(-1, color="gray", linewidth=0.5, linestyle="--")
            ax3.axvline(1, color="gray", linewidth=0.5, linestyle="--")
            ax3.set_title("Spread Z-Scores (5Y Rolling)", fontweight="bold")
            ax3.set_xlabel("Z-Score")

    # --- Panel 4: Percentile Gauge ---
    ax4 = fig.add_subplot(gs[1, 2:])
    if len(zscore_table) > 0:
        hy_ig = zscore_table[zscore_table["Universe"].isin(["US_HY", "US_IG", "EUR_HY"])]
        if len(hy_ig) > 0:
            hy_ig_sorted = hy_ig.sort_values("Pct_5Y")
            colors = ["#e74c3c" if p < 20 else "#f39c12" if p < 40 else "#95a5a6" if p < 60 else "#2ecc71" if p < 80 else "#27ae60" for p in hy_ig_sorted["Pct_5Y"]]
            ax4.barh(range(len(hy_ig_sorted)), hy_ig_sorted["Pct_5Y"].values, color=colors, edgecolor="white")
            ax4.set_yticks(range(len(hy_ig_sorted)))
            ax4.set_yticklabels(hy_ig_sorted["Index"].values, fontsize=8)
            ax4.axvline(50, color="black", linewidth=0.8, linestyle="--")
            ax4.set_title("Spread Percentile (5Y Window)", fontweight="bold")
            ax4.set_xlabel("Percentile")
            ax4.set_xlim(0, 100)

    # --- Panel 5: CCC/BB Ratio (Quality) ---
    ax5 = fig.add_subplot(gs[2, 0])
    if "US_CCC" in spreads and "US_BB" in spreads:
        ccc_bb = (spreads["US_CCC"] / spreads["US_BB"]).dropna()
        ax5.plot(ccc_bb.index, ccc_bb.values, color="#8e44ad", linewidth=1)
        ma = ccc_bb.rolling(252).mean()
        ax5.plot(ma.index, ma.values, color="gray", linewidth=0.8, linestyle="--", label="1Y MA")
        ax5.set_title("CCC/BB Spread Ratio", fontweight="bold", fontsize=10)
        ax5.legend(fontsize=7)
        ax5.grid(True, alpha=0.3)

    # --- Panel 6: HY/IG Ratio ---
    ax6 = fig.add_subplot(gs[2, 1])
    if "US_HY" in spreads and "US_IG" in spreads:
        hy_ig_r = (spreads["US_HY"] / spreads["US_IG"]).dropna()
        ax6.plot(hy_ig_r.index, hy_ig_r.values, color="#2980b9", linewidth=1)
        ma = hy_ig_r.rolling(252).mean()
        ax6.plot(ma.index, ma.values, color="gray", linewidth=0.8, linestyle="--", label="1Y MA")
        ax6.set_title("HY/IG Spread Ratio", fontweight="bold", fontsize=10)
        ax6.legend(fontsize=7)
        ax6.grid(True, alpha=0.3)

    # --- Panel 7: BBB OAS (Fallen Angel boundary) ---
    ax7 = fig.add_subplot(gs[2, 2])
    if "US_BBB" in spreads:
        s = spreads["US_BBB"].dropna()
        ax7.plot(s.index, s.values, color="#d35400", linewidth=1.2)
        mean_val = s.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).mean()
        ax7.plot(mean_val.index, mean_val.values, color="gray", linewidth=0.8, linestyle="--", label="5Y MA")
        ax7.set_title("BBB OAS (Fallen Angel Boundary)", fontweight="bold", fontsize=10)
        ax7.legend(fontsize=7)
        ax7.grid(True, alpha=0.3)

    # --- Panel 8: EUR/US HY Ratio ---
    ax8 = fig.add_subplot(gs[2, 3])
    if "EUR_HY" in spreads and "US_HY" in spreads:
        ratio = (spreads["EUR_HY"] / spreads["US_HY"]).dropna()
        ax8.plot(ratio.index, ratio.values, color="#2c3e50", linewidth=1.2)
        ax8.axhline(ratio.rolling(ZSCORE_WINDOW_DAYS, min_periods=252).mean().dropna().iloc[-1],
                     color="red", linewidth=0.8, linestyle="--", label="5Y Mean")
        ax8.set_title("EUR HY / US HY Ratio", fontweight="bold", fontsize=10)
        ax8.legend(fontsize=7)
        ax8.grid(True, alpha=0.3)

    # --- Panel 9: Quality Rotation Signal Box ---
    ax9 = fig.add_subplot(gs[3, 0])
    ax9.set_xlim(0, 1)
    ax9.set_ylim(0, 1)
    ax9.axis("off")
    q_score = quality["composite"]
    q_color = "#27ae60" if q_score > 0.5 else "#e74c3c" if q_score < -0.5 else "#f39c12"
    box = FancyBboxPatch((0.05, 0.1), 0.9, 0.8, boxstyle="round,pad=0.05",
                          facecolor=q_color, alpha=0.2, edgecolor=q_color, linewidth=2)
    ax9.add_patch(box)
    ax9.text(0.5, 0.8, "QUALITY ROTATION", ha="center", va="center", fontsize=10, fontweight="bold")
    ax9.text(0.5, 0.6, f"{q_score:+.2f}", ha="center", va="center", fontsize=22, fontweight="bold", color=q_color)
    direction = "DOWN in quality" if q_score > 0.3 else "UP in quality" if q_score < -0.3 else "NEUTRAL"
    ax9.text(0.5, 0.35, direction, ha="center", va="center", fontsize=9, style="italic")

    # --- Panel 10: Fair Value Model Box ---
    ax10 = fig.add_subplot(gs[3, 1])
    ax10.set_xlim(0, 1)
    ax10.set_ylim(0, 1)
    ax10.axis("off")
    if "residual_z" in fair_value:
        fv_z = fair_value["residual_z"]
        fv_color = "#27ae60" if fv_z > 0.5 else "#e74c3c" if fv_z < -0.5 else "#95a5a6"
        box2 = FancyBboxPatch((0.05, 0.1), 0.9, 0.8, boxstyle="round,pad=0.05",
                               facecolor=fv_color, alpha=0.2, edgecolor=fv_color, linewidth=2)
        ax10.add_patch(box2)
        ax10.text(0.5, 0.8, "FAIR VALUE MODEL", ha="center", va="center", fontsize=10, fontweight="bold")
        ax10.text(0.5, 0.6, f"{fair_value['residual_US_HY']:+.0f}bps", ha="center", va="center", fontsize=20, fontweight="bold", color=fv_color)
        ax10.text(0.5, 0.42, f"Z={fv_z:+.2f}", ha="center", va="center", fontsize=12)
        label = "CHEAP" if fv_z > 0.5 else "RICH" if fv_z < -0.5 else "FAIR"
        ax10.text(0.5, 0.25, label, ha="center", va="center", fontsize=11, fontweight="bold", color=fv_color)

    # --- Panel 11: Credit Curve (IG maturity buckets) ---
    ax11 = fig.add_subplot(gs[3, 2:])
    mat_keys = [("US_1_3Y", "1-3Y"), ("US_3_5Y", "3-5Y"), ("US_5_7Y", "5-7Y"),
                ("US_7_10Y", "7-10Y"), ("US_10_15Y", "10-15Y"), ("US_15Y_PLUS", "15Y+")]
    current_curve = []
    labels = []
    for key, label in mat_keys:
        if key in spreads:
            val = spreads[key].dropna().iloc[-1] if len(spreads[key].dropna()) > 0 else np.nan
            if not pd.isna(val):
                current_curve.append(val)
                labels.append(label)
    if current_curve:
        ax11.bar(range(len(current_curve)), current_curve, color="#3498db", edgecolor="white")
        ax11.set_xticks(range(len(labels)))
        ax11.set_xticklabels(labels, fontsize=9)
        ax11.set_ylabel("OAS (bps)")
        ax11.set_title("US IG Credit Curve (OAS by Maturity)", fontweight="bold", fontsize=10)
        ax11.grid(True, alpha=0.3, axis="y")

    plt.savefig("hy_fair_value_dashboard.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: hy_fair_value_dashboard.png")
    plt.close()


# =============================================================================
# MAIN
# =============================================================================


def main():
    print("\n" + "=" * 70)
    print("  HIGH-YIELD FAIR VALUE & Z-SCORE MODEL")
    print("  Focus: US HY (BB/B/CCC) + Euro HY + Quality Rotation")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  History: {HISTORY_YEARS} years")
    print()

    # 1. Fetch data
    spreads, funds = fetch_data()

    # 2. Z-Score model
    print("\n  Computing Z-scores and percentiles...")
    zscore_table = compute_spread_zscores(spreads)

    # 3. Spread decomposition
    print("  Decomposing spreads into components...")
    decomp_table = spread_decomposition_table(spreads)

    # 4. Fair value regression
    print("  Running fundamental fair value regression...")
    fair_value = fair_value_regression(spreads, funds)

    # 5. Quality rotation
    print("  Computing quality rotation signal...")
    quality = quality_rotation_signal(spreads, funds)

    # 6. Print full report
    rich_cheap_scorecard(zscore_table, decomp_table, fair_value, quality)

    # 7. Visualization
    print("\n  Generating dashboard chart...")
    plot_dashboard(spreads, zscore_table, fair_value, quality)

    # 8. Save data
    zscore_table.to_csv("hy_zscore_table.csv", index=False)
    decomp_table.to_csv("hy_decomposition.csv", index=False)
    print(f"  Z-Score table saved: hy_zscore_table.csv")
    print(f"  Decomposition saved: hy_decomposition.csv")

    print("\n  DONE.\n")


if __name__ == "__main__":
    main()
