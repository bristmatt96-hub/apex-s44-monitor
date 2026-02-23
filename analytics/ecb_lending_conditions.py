#!/usr/bin/env python3
"""
Module 15: ECB Lending Conditions Monitor
==========================================
Tracks ECB Bank Lending Survey, MFI balance sheet data, supervisory NPL ratios,
and Eurostat industrial production by NACE sector. Builds a composite lending
conditions indicator and sector-specific leading indicators for iTraxx Crossover
credit analysis.

Data Sources:
  - ECB Statistical Data Warehouse (via ecbdata)
  - Eurostat (via eurostat library)

Dependencies:
  - crossover_constituents.py (for sector mapping)
  - pip install ecbdata eurostat pandas matplotlib numpy

Usage:
  python ecb_lending_conditions.py

Author: Built with Claude for European credit trading
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

try:
    from ecbdata import ecbdata
except ImportError:
    try:
        import ecbdata as _ecbdata_mod
        ecbdata = _ecbdata_mod
    except ImportError:
        print("ERROR: pip install ecbdata")
        sys.exit(1)

try:
    import eurostat
except ImportError:
    print("ERROR: pip install eurostat")
    sys.exit(1)

warnings.filterwarnings("ignore")


# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_START = "2003-01-01"

# --- ECB Bank Lending Survey (BLS) series --- quarterly
# Note: ECB public API (ecbdata) only serves EA aggregates for BLS with WFNET.
# Country-level BLS not available via API. We use EA aggregate BLS + country BSI.
BLS_SERIES = {
    "EA_ENT_STANDARDS": {
        "key": "BLS.Q.U2.ALL.O.E.Z.B3.ST.S.WFNET",
        "name": "EA Enterprise Credit Standards (net tightening %)",
        "signal_dir": "negative",
        "category": "bls_standards",
    },
    "EA_ENT_TERMS": {
        "key": "BLS.Q.U2.ALL.O.E.Z.B3.TC.S.WFNET",
        "name": "EA Enterprise Credit Terms & Conditions (net tightening %)",
        "signal_dir": "negative",
        "category": "bls_terms",
    },
}

# --- MFI Balance Sheet (BSI) series --- monthly
BSI_SERIES = {
    "EA_NFC_LOAN_GROWTH": {
        "key": "BSI.M.U2.N.A.A20.A.I.U2.2240.Z01.A",
        "name": "EA NFC Loan Growth (annual %)",
        "signal_dir": "positive",
        "category": "bsi_credit",
    },
    "DE_NFC_LOAN_GROWTH": {
        "key": "BSI.M.DE.N.A.A20.A.I.U2.2240.Z01.A",
        "name": "DE NFC Loan Growth",
        "signal_dir": "positive",
        "category": "bsi_credit",
    },
    "FR_NFC_LOAN_GROWTH": {
        "key": "BSI.M.FR.N.A.A20.A.I.U2.2240.Z01.A",
        "name": "FR NFC Loan Growth",
        "signal_dir": "positive",
        "category": "bsi_credit",
    },
    "IT_NFC_LOAN_GROWTH": {
        "key": "BSI.M.IT.N.A.A20.A.I.U2.2240.Z01.A",
        "name": "IT NFC Loan Growth",
        "signal_dir": "positive",
        "category": "bsi_credit",
    },
    "ES_NFC_LOAN_GROWTH": {
        "key": "BSI.M.ES.N.A.A20.A.I.U2.2240.Z01.A",
        "name": "ES NFC Loan Growth",
        "signal_dir": "positive",
        "category": "bsi_credit",
    },
}

# --- Supervisory NPL ---
SUP_SERIES = {
    "EA_NPL_RATIO": {
        "key": "SUP.Q.B01.W0._Z.I7005._T.SII._Z._Z._Z.PCT.C",
        "name": "EA NPL Ratio (%)",
        "signal_dir": "negative",
        "category": "asset_quality",
    },
}

# --- Crossover sector -> NACE code mapping ---
SECTOR_NACE_MAP = {
    "Autos":       {"nace": "C29",  "name": "Motor vehicles"},
    "Metals":      {"nace": "C24",  "name": "Basic metals"},
    "Chemicals":   {"nace": "C20",  "name": "Chemicals"},
    "Building":    {"nace": "C23",  "name": "Non-metallic minerals"},
    "Packaging":   {"nace": "C22",  "name": "Rubber & plastics"},
    "Industrials": {"nace": "C28",  "name": "Machinery"},
    "Healthcare":  {"nace": "C21",  "name": "Pharmaceuticals"},
    "Aerospace":   {"nace": "C30",  "name": "Other transport equip"},
    "Technology":  {"nace": "C26",  "name": "Computer/electronics"},
}

EUROSTAT_COUNTRIES = ["DE", "FR", "IT", "ES"]
EUROSTAT_DATASET = "sts_inpr_m"

# Composite weights (adjusted for available data)
# BLS standards + terms give lending supply picture
# BSI growth gives credit flow picture
# NPL gives asset quality picture
COMPOSITE_WEIGHTS = {
    "bls_standards": 0.30,
    "bls_terms": 0.15,
    "bsi_growth": 0.35,
    "npl_ratio": 0.20,
}

# Lending regime thresholds (composite Z-score)
REGIME_THRESHOLDS = [
    (1.0,  "TIGHT"),
    (0.3,  "TIGHTENING"),
    (-0.3, "NEUTRAL"),
    (-1.0, "EASING"),
    (float("-inf"), "EASY"),
]

# Chart styling
CHART_BG = "#1a1a2e"
CHART_FG = "#e0e0e0"
ACCENT_BLUE = "#4fc3f7"
ACCENT_RED = "#ef5350"
ACCENT_GREEN = "#66bb6a"
ACCENT_ORANGE = "#ffa726"


# =============================================================================
# DATA FETCHING - ECB
# =============================================================================

def fetch_ecb_series(series_key: str, start: str = HISTORY_START) -> Optional[pd.Series]:
    """Fetch a single ECB series via ecbdata. Returns date-indexed pd.Series or None."""
    try:
        df = ecbdata.get_series(series_key, start=start)
        if df is None or len(df) == 0:
            return None
        if isinstance(df, pd.DataFrame):
            # ecbdata returns DataFrame with OBS_VALUE and TIME_PERIOD columns
            if "OBS_VALUE" in df.columns and "TIME_PERIOD" in df.columns:
                vals = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
                idx = pd.to_datetime(df["TIME_PERIOD"], errors="coerce")
                result = pd.Series(vals.values, index=idx, name=series_key)
                return result.dropna().sort_index()
            # Fallback: find any numeric column
            for col in df.columns:
                if col in ("TIME_PERIOD", "FREQ", "REF_AREA", "KEY"):
                    continue
                vals = pd.to_numeric(df[col], errors="coerce")
                if vals.notna().sum() > 0:
                    if "TIME_PERIOD" in df.columns:
                        idx = pd.to_datetime(df["TIME_PERIOD"], errors="coerce")
                        result = pd.Series(vals.values, index=idx, name=series_key)
                    else:
                        result = pd.Series(vals.values, name=series_key)
                    return result.dropna().sort_index()
        elif isinstance(df, pd.Series):
            return df.dropna()
        return None
    except Exception as e:
        print(f"    WARNING: Failed to fetch {series_key}: {e}")
        return None


def fetch_all_ecb_data() -> Dict[str, pd.Series]:
    """Fetch all BLS + BSI + SUP series from ECB."""
    all_data = {}
    all_series = {}
    all_series.update(BLS_SERIES)
    all_series.update(BSI_SERIES)
    all_series.update(SUP_SERIES)

    total = len(all_series)
    print(f"\n  Fetching {total} ECB series...")

    for i, (sid, info) in enumerate(all_series.items(), 1):
        print(f"    [{i:02d}/{total}] {info['name'][:50]}...", end=" ")
        s = fetch_ecb_series(info["key"])
        if s is not None and len(s) > 0:
            all_data[sid] = s
            print(f"OK ({len(s)} obs)")
        else:
            print("FAILED")

    print(f"  -> {len(all_data)}/{total} series fetched successfully")
    return all_data


# =============================================================================
# DATA FETCHING - EUROSTAT
# =============================================================================

def fetch_eurostat_production(nace_code: str, country: str,
                               start_year: int = 2003) -> Optional[pd.Series]:
    """Fetch monthly industrial production index for a NACE sector/country."""
    try:
        filter_pars = {
            "nace_r2": [nace_code],
            "geo": [country],
            "unit": ["I15"],      # Index 2015=100
            "s_adj": ["SCA"],     # Seasonally and calendar adjusted
        }
        df = eurostat.get_data_df(EUROSTAT_DATASET, filter_pars=filter_pars)
        if df is None or len(df) == 0:
            return None

        # Eurostat returns wide format with date columns
        # Find time columns (format like '2024-01', '2024M01', etc.)
        time_cols = []
        for col in df.columns:
            col_str = str(col)
            if len(col_str) >= 6 and (col_str[:4].isdigit()):
                time_cols.append(col)

        if not time_cols:
            # Try using backslash-separated format or 'time' column
            if "time" in df.columns.str.lower().tolist():
                return None
            return None

        # Melt to long format
        values = []
        dates = []
        for tc in sorted(time_cols):
            tc_str = str(tc).replace("M", "-").replace(" ", "")
            try:
                dt = pd.to_datetime(tc_str, format="%Y-%m")
            except Exception:
                try:
                    dt = pd.to_datetime(tc_str)
                except Exception:
                    continue
            val = pd.to_numeric(df.iloc[0][tc], errors="coerce")
            if pd.notna(val) and dt.year >= start_year:
                dates.append(dt)
                values.append(val)

        if len(values) > 0:
            return pd.Series(values, index=pd.DatetimeIndex(dates),
                           name=f"{country}_{nace_code}").sort_index()
        return None
    except Exception as e:
        return None


def fetch_all_eurostat_data() -> Dict[str, pd.Series]:
    """Fetch all sector x country Eurostat production series."""
    all_data = {}
    combos = [(sector, info["nace"], cc)
              for sector, info in SECTOR_NACE_MAP.items()
              for cc in EUROSTAT_COUNTRIES]
    total = len(combos)
    print(f"\n  Fetching {total} Eurostat production series...")

    for i, (sector, nace, cc) in enumerate(combos, 1):
        key = f"{cc}_{nace}"
        s = fetch_eurostat_production(nace, cc)
        if s is not None and len(s) > 5:
            all_data[key] = s
            if i % 10 == 0 or i == total:
                print(f"    [{i:02d}/{total}] fetched...")

    print(f"  -> {len(all_data)}/{total} Eurostat series fetched successfully")
    return all_data


# =============================================================================
# COMPUTATION - Z-SCORES AND COMPOSITE
# =============================================================================

def compute_zscore(series: pd.Series, lookback: int = 40) -> pd.Series:
    """Rolling Z-score. lookback in same frequency as the series."""
    rolling_mean = series.rolling(lookback, min_periods=max(8, lookback // 3)).mean()
    rolling_std = series.rolling(lookback, min_periods=max(8, lookback // 3)).std()
    z = (series - rolling_mean) / rolling_std.replace(0, np.nan)
    return z.clip(-4, 4)


def compute_momentum(series: pd.Series, periods: int = 4) -> pd.Series:
    """N-period change (momentum)."""
    return series.diff(periods)


def classify_regime(z: float) -> str:
    """Classify lending regime from composite Z-score."""
    for threshold, label in REGIME_THRESHOLDS:
        if z >= threshold:
            return label
    return "EASY"


def build_lending_composite(ecb_data: Dict[str, pd.Series]) -> pd.DataFrame:
    """Build composite lending conditions indicator.

    Composite = weighted average of:
      BLS standards Z (30%, tightening = positive Z = bad for credit)
      BLS terms Z (15%, tightening = positive Z = bad)
      BSI loan growth Z (35%, inverted: falling growth = positive Z = bad)
      NPL ratio Z (20%, higher = worse)
    """
    # Get EA-level series for each component
    bls_std = ecb_data.get("EA_ENT_STANDARDS")
    bls_terms = ecb_data.get("EA_ENT_TERMS")
    bsi_growth = ecb_data.get("EA_NFC_LOAN_GROWTH")
    npl = ecb_data.get("EA_NPL_RATIO")

    # Determine the common quarterly date range
    # BLS is quarterly; BSI is monthly (resample to quarterly)
    components = {}

    if bls_std is not None and len(bls_std) > 10:
        z = compute_zscore(bls_std, lookback=40)
        components["bls_standards_z"] = z  # positive = tightening = bad for credit

    if bls_terms is not None and len(bls_terms) > 10:
        z = compute_zscore(bls_terms, lookback=40)
        components["bls_terms_z"] = z  # positive = tightening terms = bad

    if bsi_growth is not None and len(bsi_growth) > 20:
        # Resample monthly to quarterly (last value)
        q = bsi_growth.resample("QE").last().dropna()
        z = compute_zscore(q, lookback=40)
        components["bsi_growth_z"] = -z  # invert: falling growth = positive Z = bad

    if npl is not None and len(npl) > 10:
        z = compute_zscore(npl, lookback=40)
        components["npl_z"] = z  # positive = rising NPLs = bad

    if len(components) == 0:
        print("  WARNING: No ECB components available for composite")
        return pd.DataFrame()

    # Align all to quarterly
    comp_df = pd.DataFrame(components)
    comp_df = comp_df.dropna(how="all")

    # Compute composite
    weights = {
        "bls_standards_z": COMPOSITE_WEIGHTS["bls_standards"],
        "bls_terms_z": COMPOSITE_WEIGHTS["bls_terms"],
        "bsi_growth_z": COMPOSITE_WEIGHTS["bsi_growth"],
        "npl_z": COMPOSITE_WEIGHTS["npl_ratio"],
    }

    weighted_sum = pd.Series(0.0, index=comp_df.index)
    total_weight = 0.0
    for col, w in weights.items():
        if col in comp_df.columns:
            filled = comp_df[col].ffill()
            weighted_sum += filled.fillna(0) * w
            total_weight += w

    if total_weight > 0:
        comp_df["composite_z"] = weighted_sum / total_weight
    else:
        comp_df["composite_z"] = 0.0

    comp_df["composite_momentum"] = compute_momentum(comp_df["composite_z"], periods=4)
    comp_df["lending_regime"] = comp_df["composite_z"].apply(classify_regime)
    comp_df["date"] = comp_df.index

    return comp_df.reset_index(drop=True)


def build_sector_indicators(eurostat_data: Dict[str, pd.Series],
                             ecb_data: Dict[str, pd.Series]) -> pd.DataFrame:
    """Build sector-specific leading indicators from Eurostat production data."""
    rows = []

    for sector, info in SECTOR_NACE_MAP.items():
        nace = info["nace"]
        prod_z_list = []
        prod_mom_list = []

        for cc in EUROSTAT_COUNTRIES:
            key = f"{cc}_{nace}"
            if key in eurostat_data:
                s = eurostat_data[key]
                if len(s) > 24:
                    z = compute_zscore(s, lookback=60)  # 5 years monthly
                    mom = compute_momentum(s, periods=12)  # 12-month change
                    if pd.notna(z.iloc[-1]):
                        prod_z_list.append(z.iloc[-1])
                    if pd.notna(mom.iloc[-1]):
                        prod_mom_list.append(mom.iloc[-1])

        prod_z = np.mean(prod_z_list) if prod_z_list else np.nan
        prod_mom = np.mean(prod_mom_list) if prod_mom_list else np.nan

        # Get BLS overlay for the sector
        bls_z = np.nan
        if "EA_ENT_STANDARDS" in ecb_data:
            bls = ecb_data["EA_ENT_STANDARDS"]
            if len(bls) > 10:
                z_series = compute_zscore(bls, lookback=40)
                bls_z = z_series.iloc[-1] if pd.notna(z_series.iloc[-1]) else np.nan

        # Sector composite: 60% production + 40% BLS
        sector_comp = 0.0
        n = 0
        if not np.isnan(prod_z):
            sector_comp -= prod_z * 0.6  # negative production = bad = positive composite
            n += 1
        if not np.isnan(bls_z):
            sector_comp += bls_z * 0.4   # positive BLS (tightening) = bad
            n += 1
        if n == 0:
            sector_comp = np.nan

        # Classify outlook
        if np.isnan(sector_comp):
            outlook = "NO DATA"
        elif sector_comp >= 1.0:
            outlook = "VERY NEGATIVE"
        elif sector_comp >= 0.3:
            outlook = "NEGATIVE"
        elif sector_comp >= -0.3:
            outlook = "NEUTRAL"
        elif sector_comp >= -1.0:
            outlook = "POSITIVE"
        else:
            outlook = "VERY POSITIVE"

        rows.append({
            "sector": sector,
            "nace": nace,
            "nace_name": info["name"],
            "production_z": round(prod_z, 2) if not np.isnan(prod_z) else np.nan,
            "production_mom": round(prod_mom, 1) if not np.isnan(prod_mom) else np.nan,
            "bls_z": round(bls_z, 2) if not np.isnan(bls_z) else np.nan,
            "sector_composite": round(sector_comp, 2) if not np.isnan(sector_comp) else np.nan,
            "outlook": outlook,
            "n_countries": len(prod_z_list),
        })

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("sector_composite", ascending=False, na_position="last")
    return df


def country_lending_heatmap(ecb_data: Dict[str, pd.Series]) -> pd.DataFrame:
    """Build country x metric heatmap. Rows = countries, cols = metric Z-scores."""
    countries = {"DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain"}
    rows = []

    for cc, name in countries.items():
        row = {"country": cc, "name": name}

        # BLS standards
        sid = f"{cc}_ENT_STANDARDS"
        if sid in ecb_data and len(ecb_data[sid]) > 10:
            z = compute_zscore(ecb_data[sid], lookback=40)
            row["standards_z"] = round(z.iloc[-1], 2) if pd.notna(z.iloc[-1]) else np.nan
        else:
            row["standards_z"] = np.nan

        # BSI loan growth
        sid = f"{cc}_NFC_LOAN_GROWTH"
        if sid in ecb_data and len(ecb_data[sid]) > 20:
            z = compute_zscore(ecb_data[sid], lookback=60)
            row["growth_z"] = round(z.iloc[-1], 2) if pd.notna(z.iloc[-1]) else np.nan
            row["growth_latest"] = round(ecb_data[sid].iloc[-1], 1)
        else:
            row["growth_z"] = np.nan
            row["growth_latest"] = np.nan

        rows.append(row)

    # Add EA aggregate
    ea_row = {"country": "EA", "name": "Euro Area"}
    if "EA_ENT_STANDARDS" in ecb_data and len(ecb_data["EA_ENT_STANDARDS"]) > 10:
        z = compute_zscore(ecb_data["EA_ENT_STANDARDS"], lookback=40)
        ea_row["standards_z"] = round(z.iloc[-1], 2) if pd.notna(z.iloc[-1]) else np.nan
    else:
        ea_row["standards_z"] = np.nan

    if "EA_NFC_LOAN_GROWTH" in ecb_data and len(ecb_data["EA_NFC_LOAN_GROWTH"]) > 20:
        z = compute_zscore(ecb_data["EA_NFC_LOAN_GROWTH"], lookback=60)
        ea_row["growth_z"] = round(z.iloc[-1], 2) if pd.notna(z.iloc[-1]) else np.nan
        ea_row["growth_latest"] = round(ecb_data["EA_NFC_LOAN_GROWTH"].iloc[-1], 1)
    else:
        ea_row["growth_z"] = np.nan
        ea_row["growth_latest"] = np.nan

    rows.insert(0, ea_row)
    return pd.DataFrame(rows)


def regime_spread_analysis(ecb_data: Dict[str, pd.Series]) -> Dict:
    """Analyze historical relationship: BLS tightening -> HY spreads.

    Since we don't have HY spread data here (that's in the FRED modules),
    we compute descriptive statistics on the BLS standards series and
    identify tightening episodes.
    """
    result = {
        "avg_lead_months": "6-9",
        "tightening_episodes": [],
        "current_signal": "N/A",
        "historical_note": "BLS tightening historically leads HY spread widening by 6-9 months",
    }

    bls = ecb_data.get("EA_ENT_STANDARDS")
    if bls is None or len(bls) < 20:
        return result

    # Identify tightening episodes: consecutive quarters with positive net tightening
    episodes = []
    in_episode = False
    ep_start = None
    for i in range(len(bls)):
        val = bls.iloc[i]
        if val > 10:  # >10% net tightening
            if not in_episode:
                in_episode = True
                ep_start = bls.index[i]
        else:
            if in_episode:
                in_episode = False
                episodes.append({
                    "start": str(ep_start)[:10],
                    "end": str(bls.index[i - 1])[:10],
                    "peak_tightening": round(bls.iloc[max(0, i-5):i].max(), 1),
                })

    result["tightening_episodes"] = episodes[-5:]  # Last 5 episodes
    result["n_episodes"] = len(episodes)

    # Current signal
    latest = bls.iloc[-1]
    if latest > 20:
        result["current_signal"] = "STRONG TIGHTENING"
    elif latest > 5:
        result["current_signal"] = "MODERATE TIGHTENING"
    elif latest > -5:
        result["current_signal"] = "NEUTRAL"
    elif latest > -20:
        result["current_signal"] = "MODERATE EASING"
    else:
        result["current_signal"] = "STRONG EASING"
    result["latest_bls_value"] = round(latest, 1)

    return result


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(composite_df: pd.DataFrame, sector_df: pd.DataFrame,
                  country_df: pd.DataFrame, regime_analysis: Dict,
                  ecb_data: Dict[str, pd.Series]):
    """Print full ECB lending conditions report."""
    w = 100
    print("\n" + "=" * w)
    print("  ECB LENDING CONDITIONS MONITOR - EURO AREA")
    print("=" * w)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  ECB series fetched: {len(ecb_data)}")

    # 1. COMPOSITE
    print("\n" + "=" * w)
    print("  1. LENDING CONDITIONS COMPOSITE")
    print("=" * w)

    if len(composite_df) > 0:
        latest = composite_df.iloc[-1]
        print(f"  Current Regime:     {latest.get('lending_regime', 'N/A')}")
        print(f"  Composite Z-Score:  {latest.get('composite_z', 0):.2f}")
        print(f"  Momentum (4Q):      {latest.get('composite_momentum', 0):.2f}")

        for col in ["bls_standards_z", "bls_terms_z", "bsi_growth_z", "npl_z"]:
            if col in composite_df.columns:
                val = latest.get(col, np.nan)
                if pd.notna(val):
                    print(f"  {col:24s} {val:+.2f}")

        print(f"\n  Last 8 quarters:")
        tail = composite_df.tail(8)
        for _, row in tail.iterrows():
            d = str(row.get("date", ""))[:10]
            cz = row.get("composite_z", np.nan)
            regime = row.get("lending_regime", "")
            if pd.notna(cz):
                print(f"    {d}  Z={cz:+.2f}  {regime}")
    else:
        print("  No composite data available")

    # 2. BLS STANDARDS & TERMS
    print("\n" + "=" * w)
    print("  2. BLS ENTERPRISE CREDIT SURVEY (net % tightening)")
    print("=" * w)
    for sid in ["EA_ENT_STANDARDS", "EA_ENT_TERMS"]:
        if sid in ecb_data:
            s = ecb_data[sid]
            info = {**BLS_SERIES.get(sid, {})}
            name = info.get("name", sid)[:50]
            latest = s.iloc[-1]
            prev = s.iloc[-2] if len(s) > 1 else np.nan
            chg = latest - prev if pd.notna(prev) else np.nan
            chg_str = f"{chg:+.1f}" if pd.notna(chg) else "N/A"
            print(f"  {name:52s} Latest={latest:+6.1f}  Chg={chg_str}")
    print(f"\n  Note: Country-level BLS not available via ECB public API.")
    print(f"  Country differentiation from BSI loan growth data (section 3).")

    # 3. BSI LOAN GROWTH
    print("\n" + "=" * w)
    print("  3. BSI NFC LOAN GROWTH (annual %)")
    print("=" * w)
    for sid in ["EA_NFC_LOAN_GROWTH", "DE_NFC_LOAN_GROWTH", "FR_NFC_LOAN_GROWTH",
                "IT_NFC_LOAN_GROWTH", "ES_NFC_LOAN_GROWTH"]:
        if sid in ecb_data:
            s = ecb_data[sid]
            info = {**BSI_SERIES.get(sid, {})}
            name = info.get("name", sid)[:40]
            latest = s.iloc[-1]
            print(f"  {name:42s} Latest={latest:+6.1f}%")

    # 4. SECTOR PRODUCTION
    print("\n" + "=" * w)
    print("  4. SECTOR PRODUCTION INDICATORS")
    print("=" * w)
    if len(sector_df) > 0:
        print(f"  {'Sector':<15s} {'NACE':<6s} {'Prod Z':<8s} {'Mom 12m':<9s} {'BLS Z':<8s} {'Composite':<10s} {'Outlook':<15s} CC")
        print("  " + "-" * 85)
        for _, row in sector_df.iterrows():
            pz = f"{row['production_z']:+.2f}" if pd.notna(row["production_z"]) else "  N/A"
            pm = f"{row['production_mom']:+.1f}" if pd.notna(row["production_mom"]) else "  N/A"
            bz = f"{row['bls_z']:+.2f}" if pd.notna(row["bls_z"]) else "  N/A"
            sc = f"{row['sector_composite']:+.2f}" if pd.notna(row["sector_composite"]) else "  N/A"
            print(f"  {row['sector']:<15s} {row['nace']:<6s} {pz:>7s} {pm:>8s} {bz:>7s} {sc:>9s} {row['outlook']:<15s} {row['n_countries']}")
    else:
        print("  No Eurostat data available")

    # 5. COUNTRY HEATMAP
    print("\n" + "=" * w)
    print("  5. COUNTRY LENDING HEATMAP")
    print("=" * w)
    if len(country_df) > 0:
        print(f"  {'Country':<12s} {'Standards Z':<14s} {'Growth Z':<12s} {'Growth Latest':<14s}")
        print("  " + "-" * 55)
        for _, row in country_df.iterrows():
            sz = f"{row['standards_z']:+.2f}" if pd.notna(row.get("standards_z")) else "N/A"
            gz = f"{row['growth_z']:+.2f}" if pd.notna(row.get("growth_z")) else "N/A"
            gl = f"{row['growth_latest']:+.1f}%" if pd.notna(row.get("growth_latest")) else "N/A"
            print(f"  {row['name']:<12s} {sz:>12s} {gz:>10s} {gl:>12s}")

    # 6. REGIME-SPREAD ANALYSIS
    print("\n" + "=" * w)
    print("  6. REGIME-SPREAD LEAD/LAG ANALYSIS")
    print("=" * w)
    print(f"  Historical lead time: {regime_analysis.get('avg_lead_months', 'N/A')} months")
    print(f"  Current BLS signal:   {regime_analysis.get('current_signal', 'N/A')}")
    latest_bls = regime_analysis.get("latest_bls_value")
    if latest_bls is not None:
        print(f"  Latest BLS value:     {latest_bls:+.1f}%")
    print(f"  Total tightening episodes since 2003: {regime_analysis.get('n_episodes', 0)}")

    episodes = regime_analysis.get("tightening_episodes", [])
    if episodes:
        print(f"\n  Recent tightening episodes:")
        for ep in episodes:
            print(f"    {ep['start']} to {ep['end']}  (peak: {ep['peak_tightening']:+.1f}%)")

    # 7. IMPLICATIONS
    print("\n" + "=" * w)
    print("  7. iTRAXX CROSSOVER IMPLICATIONS")
    print("=" * w)
    if len(composite_df) > 0:
        latest = composite_df.iloc[-1]
        regime = latest.get("lending_regime", "N/A")
        cz = latest.get("composite_z", 0)
        mom = latest.get("composite_momentum", 0)

        if regime in ("TIGHT", "TIGHTENING"):
            print("  -> CAUTION: Lending conditions are tight/tightening")
            print("     Historically leads HY spread widening by 6-9 months")
            print("     Consider: Reduce HY beta, favor short-dated, focus on quality")
        elif regime in ("EASY", "EASING"):
            print("  -> SUPPORTIVE: Lending conditions are easy/easing")
            print("     Positive for credit fundamentals and refinancing")
            print("     Consider: Overweight HY, favor spread compression trades")
        else:
            print("  -> NEUTRAL: Lending conditions are balanced")
            print("     No strong directional signal from ECB lending data")

        if pd.notna(mom) and mom > 0.5:
            print("  -> DETERIORATING MOMENTUM: Composite is worsening quarter-over-quarter")
        elif pd.notna(mom) and mom < -0.5:
            print("  -> IMPROVING MOMENTUM: Composite is improving quarter-over-quarter")

    print("\n" + "=" * w)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(composite_df: pd.DataFrame, sector_df: pd.DataFrame,
                    country_df: pd.DataFrame, ecb_data: Dict[str, pd.Series],
                    regime_analysis: Dict):
    """Create 6-panel ECB lending conditions dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.patch.set_facecolor(CHART_BG)
    gs = gridspec.GridSpec(3, 2, hspace=0.35, wspace=0.25,
                           left=0.06, right=0.96, top=0.93, bottom=0.05)

    fig.suptitle("ECB LENDING CONDITIONS MONITOR",
                 color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.97,
                 fontfamily="monospace")

    # --- Panel 1: Lending Composite Time Series ---
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor(CHART_BG)
    ax1.set_title("Lending Composite Z-Score", color=CHART_FG, fontsize=11)

    if len(composite_df) > 0 and "composite_z" in composite_df.columns:
        dates = composite_df["date"]
        cz = composite_df["composite_z"]
        ax1.fill_between(dates, 0, cz, where=(cz > 0), color=ACCENT_RED, alpha=0.3, label="Tight")
        ax1.fill_between(dates, 0, cz, where=(cz < 0), color=ACCENT_GREEN, alpha=0.3, label="Easy")
        ax1.plot(dates, cz, color=ACCENT_BLUE, linewidth=2, label="Composite Z")
        ax1.axhline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
        ax1.axhline(1.0, color=ACCENT_RED, linewidth=0.5, linestyle="--", alpha=0.5)
        ax1.axhline(-1.0, color=ACCENT_GREEN, linewidth=0.5, linestyle="--", alpha=0.5)
        ax1.legend(fontsize=8, loc="upper left", facecolor=CHART_BG, edgecolor=CHART_FG,
                  labelcolor=CHART_FG)

    ax1.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax1.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 2: Summary Box ---
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor(CHART_BG)
    ax2.axis("off")
    ax2.set_title("Summary", color=CHART_FG, fontsize=11)

    if len(composite_df) > 0:
        latest = composite_df.iloc[-1]
        regime = latest.get("lending_regime", "N/A")
        cz = latest.get("composite_z", 0)
        mom = latest.get("composite_momentum", 0)

        regime_color = ACCENT_RED if regime in ("TIGHT", "TIGHTENING") else \
                       ACCENT_GREEN if regime in ("EASY", "EASING") else ACCENT_ORANGE

        lines = [
            f"Lending Regime: {regime}",
            f"Composite Z: {cz:+.2f}",
            f"Momentum (4Q): {mom:+.2f}" if pd.notna(mom) else "Momentum: N/A",
            f"",
            f"BLS Current Signal: {regime_analysis.get('current_signal', 'N/A')}",
            f"Latest BLS Value: {regime_analysis.get('latest_bls_value', 'N/A')}%",
            f"Historical Lead: {regime_analysis.get('avg_lead_months', 'N/A')} months",
            f"Tightening Episodes: {regime_analysis.get('n_episodes', 0)}",
            f"",
            f"ECB Series Fetched: {len(ecb_data)}",
        ]
        for i, line in enumerate(lines):
            color = regime_color if i == 0 else CHART_FG
            ax2.text(0.05, 0.92 - i * 0.09, line, transform=ax2.transAxes,
                    fontsize=11, color=color, fontfamily="monospace", va="top")

    # --- Panel 3: BLS Credit Standards & Terms ---
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor(CHART_BG)
    ax3.set_title("BLS Enterprise Survey (net tightening %)", color=CHART_FG, fontsize=11)

    bls_plot = {
        "EA_ENT_STANDARDS": (ACCENT_BLUE, 2.0, "Credit Standards"),
        "EA_ENT_TERMS": (ACCENT_ORANGE, 1.5, "Terms & Conditions"),
    }
    for sid, (color, lw, label) in bls_plot.items():
        if sid in ecb_data:
            s = ecb_data[sid]
            ax3.plot(s.index, s.values, color=color, linewidth=lw, label=label, alpha=0.9)

    ax3.axhline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
    ax3.legend(fontsize=8, loc="upper left", facecolor=CHART_BG, edgecolor=CHART_FG,
              labelcolor=CHART_FG)
    ax3.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax3.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 4: BSI NFC Loan Growth ---
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor(CHART_BG)
    ax4.set_title("NFC Loan Growth by Country (annual %)", color=CHART_FG, fontsize=11)

    bsi_colors = {"EA": ACCENT_BLUE, "DE": "#e0e0e0", "FR": "#64b5f6",
                  "IT": ACCENT_ORANGE, "ES": ACCENT_GREEN}
    for prefix, color in bsi_colors.items():
        sid = f"{prefix}_NFC_LOAN_GROWTH"
        if sid in ecb_data:
            s = ecb_data[sid]
            ax4.plot(s.index, s.values, color=color, linewidth=1.5 if prefix == "EA" else 1,
                    label=prefix, alpha=1.0 if prefix == "EA" else 0.7)

    ax4.axhline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
    ax4.legend(fontsize=8, loc="upper left", facecolor=CHART_BG, edgecolor=CHART_FG,
              labelcolor=CHART_FG)
    ax4.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax4.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 5: Sector Production Heatmap ---
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.set_facecolor(CHART_BG)
    ax5.set_title("Sector Production Indicators", color=CHART_FG, fontsize=11)

    if len(sector_df) > 0:
        display_df = sector_df[sector_df["production_z"].notna()].head(12)
        if len(display_df) > 0:
            sectors = display_df["sector"].tolist()
            vals = display_df["production_z"].fillna(0).tolist()
            bar_colors = [ACCENT_GREEN if v > 0 else ACCENT_RED for v in vals]
            y_pos = range(len(sectors))
            ax5.barh(y_pos, vals, color=bar_colors, alpha=0.7, height=0.6)
            ax5.set_yticks(y_pos)
            ax5.set_yticklabels(sectors, fontsize=8, color=CHART_FG)
            ax5.axvline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
            ax5.set_xlabel("Production Z-Score", color=CHART_FG, fontsize=8)
            ax5.invert_yaxis()
        else:
            ax5.text(0.5, 0.5, "No Eurostat data", ha="center", va="center",
                    color=CHART_FG, fontsize=12, transform=ax5.transAxes)
    else:
        ax5.text(0.5, 0.5, "No Eurostat data", ha="center", va="center",
                color=CHART_FG, fontsize=12, transform=ax5.transAxes)

    ax5.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax5.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 6: Country Lending Heatmap ---
    ax6 = fig.add_subplot(gs[2, 1])
    ax6.set_facecolor(CHART_BG)
    ax6.set_title("Country Lending Conditions", color=CHART_FG, fontsize=11)

    if len(country_df) > 0:
        countries_list = country_df["name"].tolist()
        metrics = ["standards_z", "growth_z"]
        metric_labels = ["BLS Standards Z", "Loan Growth Z"]

        heatmap_data = np.zeros((len(countries_list), len(metrics)))
        for i, (_, row) in enumerate(country_df.iterrows()):
            for j, m in enumerate(metrics):
                heatmap_data[i, j] = row.get(m, np.nan) if pd.notna(row.get(m)) else 0

        im = ax6.imshow(heatmap_data, aspect="auto", cmap="RdYlGn_r", vmin=-2, vmax=2)
        ax6.set_xticks(range(len(metrics)))
        ax6.set_xticklabels(metric_labels, fontsize=8, color=CHART_FG, rotation=15)
        ax6.set_yticks(range(len(countries_list)))
        ax6.set_yticklabels(countries_list, fontsize=9, color=CHART_FG)

        # Add text annotations
        for i in range(len(countries_list)):
            for j in range(len(metrics)):
                val = heatmap_data[i, j]
                ax6.text(j, i, f"{val:+.1f}", ha="center", va="center",
                        color="white" if abs(val) > 1 else CHART_FG, fontsize=9)
    else:
        ax6.text(0.5, 0.5, "No country data", ha="center", va="center",
                color=CHART_FG, fontsize=12, transform=ax6.transAxes)

    ax6.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax6.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # Save
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "ecb_lending_conditions_dashboard.png")
    plt.savefig(out_path, dpi=150, facecolor=CHART_BG, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Chart saved: ecb_lending_conditions_dashboard.png")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run ECB Lending Conditions Monitor pipeline."""
    w = 80
    print("\n" + "=" * w)
    print("  MODULE 15: ECB LENDING CONDITIONS MONITOR")
    print("  Bank Lending Survey, MFI Loan Growth, NPL Ratios, Sector Production")
    print("=" * w)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Fetch ECB data
    print("\n  Step 1: Fetching ECB data (BLS + BSI + SUP)...")
    ecb_data = fetch_all_ecb_data()

    # 2. Fetch Eurostat data
    print("\n  Step 2: Fetching Eurostat industrial production data...")
    eurostat_data = fetch_all_eurostat_data()

    # 3. Build composite
    print("\n  Step 3: Building lending composite indicator...")
    composite_df = build_lending_composite(ecb_data)
    if len(composite_df) > 0:
        print(f"  -> {len(composite_df)} quarterly observations")
    else:
        print("  -> WARNING: Could not build composite (insufficient data)")

    # 4. Build sector indicators
    print("\n  Step 4: Building sector production indicators...")
    sector_df = build_sector_indicators(eurostat_data, ecb_data)
    print(f"  -> {len(sector_df)} sectors mapped")

    # 5. Country heatmap
    print("\n  Step 5: Building country lending heatmap...")
    country_df = country_lending_heatmap(ecb_data)

    # 6. Regime analysis
    print("\n  Step 6: Analyzing regime-spread lead/lag...")
    regime_analysis = regime_spread_analysis(ecb_data)

    # 7. Report
    print_report(composite_df, sector_df, country_df, regime_analysis, ecb_data)

    # 8. Chart
    print("\n  Step 8: Generating dashboard chart...")
    plot_dashboard(composite_df, sector_df, country_df, ecb_data, regime_analysis)

    # 9. CSV
    if len(composite_df) > 0:
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "ecb_lending_conditions.csv")
        composite_df.to_csv(csv_path, index=False)
        print(f"  CSV saved: ecb_lending_conditions.csv")

    print("\n  DONE.")


if __name__ == "__main__":
    main()
