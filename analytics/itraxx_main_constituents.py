#!/usr/bin/env python3
"""
iTraxx Main Constituent Data Layer
====================================
Maintains the full 125 iTraxx Main (Investment Grade) constituents mapped to
Yahoo Finance equity tickers. Fetches equity prices, market caps, and
balance sheet data via yfinance. Computes equity-based metrics that
serve as inputs for Merton DD, CDS curve bootstrapping, and tranche pricing.

Data Source: Yahoo Finance (via yfinance)
Update: Edit MAIN_CONSTITUENTS dict at each index roll (March/September)

Usage:
  pip install yfinance pandas matplotlib numpy
  python itraxx_main_constituents.py

Author: Built with Claude for macro credit trading
"""

import os
import sys
import json
import glob
import time
import warnings
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

try:
    import yfinance as yf
except ImportError:
    print("ERROR: pip install yfinance")
    sys.exit(1)

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

HISTORY_PERIOD = "2y"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache")
CACHE_MAX_AGE_HOURS = 24
FETCH_DELAY_SEC = 0.3

# =============================================================================
# CONSTITUENT LIST
# =============================================================================
# iTraxx Europe Main (Series 42) -- 125 equally-weighted IG European CDS names.
# Covers senior unsecured debt of investment-grade corporates + financials.
# Proxy tickers from Yahoo Finance; some may need adjustment at roll dates.

MAIN_CONSTITUENTS = {
    # --- Financials: Banks (Senior) ---
    "BNP Paribas":              {"ticker": "BNP.PA",       "sector": "Banks",       "rating": "A+",   "country": "FR"},
    "Societe Generale":         {"ticker": "GLE.PA",       "sector": "Banks",       "rating": "A-",   "country": "FR"},
    "Credit Agricole":          {"ticker": "ACA.PA",       "sector": "Banks",       "rating": "A+",   "country": "FR"},
    "Deutsche Bank":            {"ticker": "DBK.DE",       "sector": "Banks",       "rating": "A-",   "country": "DE"},
    "Commerzbank":              {"ticker": "CBK.DE",       "sector": "Banks",       "rating": "BBB+", "country": "DE"},
    "Barclays":                 {"ticker": "BARC.L",       "sector": "Banks",       "rating": "A",    "country": "GB"},
    "HSBC":                     {"ticker": "HSBA.L",       "sector": "Banks",       "rating": "A+",   "country": "GB"},
    "Lloyds Banking Group":     {"ticker": "LLOY.L",       "sector": "Banks",       "rating": "A",    "country": "GB"},
    "Standard Chartered":       {"ticker": "STAN.L",       "sector": "Banks",       "rating": "A",    "country": "GB"},
    "NatWest Group":            {"ticker": "NWG.L",        "sector": "Banks",       "rating": "A",    "country": "GB"},
    "UBS Group":                {"ticker": "UBSG.SW",      "sector": "Banks",       "rating": "A+",   "country": "CH"},
    "Intesa Sanpaolo":          {"ticker": "ISP.MI",       "sector": "Banks",       "rating": "BBB",  "country": "IT"},
    "UniCredit":                {"ticker": "UCG.MI",       "sector": "Banks",       "rating": "BBB",  "country": "IT"},
    "Banco Santander":          {"ticker": "SAN.MC",       "sector": "Banks",       "rating": "A",    "country": "ES"},
    "BBVA":                     {"ticker": "BBVA.MC",      "sector": "Banks",       "rating": "A",    "country": "ES"},
    "CaixaBank":                {"ticker": "CABK.MC",      "sector": "Banks",       "rating": "BBB+", "country": "ES"},
    "ING Group":                {"ticker": "INGA.AS",      "sector": "Banks",       "rating": "A+",   "country": "NL"},
    "ABN AMRO":                 {"ticker": "ABN.AS",       "sector": "Banks",       "rating": "A",    "country": "NL"},
    "Danske Bank":              {"ticker": "DANSKE.CO",    "sector": "Banks",       "rating": "A+",   "country": "DK"},
    "Nordea":                   {"ticker": "NDA-FI.HE",    "sector": "Banks",       "rating": "AA-",  "country": "FI"},
    "Svenska Handelsbanken":    {"ticker": "SHB-A.ST",     "sector": "Banks",       "rating": "AA-",  "country": "SE"},
    "DNB Bank":                 {"ticker": "DNB.OL",       "sector": "Banks",       "rating": "AA-",  "country": "NO"},

    # --- Financials: Insurance ---
    "AXA":                      {"ticker": "CS.PA",        "sector": "Insurance",   "rating": "A+",   "country": "FR"},
    "Allianz":                  {"ticker": "ALV.DE",       "sector": "Insurance",   "rating": "AA",   "country": "DE"},
    "Zurich Insurance":         {"ticker": "ZURN.SW",      "sector": "Insurance",   "rating": "AA-",  "country": "CH"},
    "Aviva":                    {"ticker": "AV.L",         "sector": "Insurance",   "rating": "A-",   "country": "GB"},
    "Legal & General":          {"ticker": "LGEN.L",       "sector": "Insurance",   "rating": "A",    "country": "GB"},
    "Prudential":               {"ticker": "PRU.L",        "sector": "Insurance",   "rating": "A",    "country": "GB"},
    "Swiss Re":                 {"ticker": "SREN.SW",      "sector": "Insurance",   "rating": "AA-",  "country": "CH"},
    "Munich Re":                {"ticker": "MUV2.DE",      "sector": "Insurance",   "rating": "AA-",  "country": "DE"},
    "Generali":                 {"ticker": "G.MI",         "sector": "Insurance",   "rating": "A-",   "country": "IT"},
    "Hannover Rueck":           {"ticker": "HNR1.DE",      "sector": "Insurance",   "rating": "AA-",  "country": "DE"},

    # --- Autos ---
    "Volkswagen":               {"ticker": "VOW3.DE",      "sector": "Autos",       "rating": "BBB+", "country": "DE"},
    "BMW":                      {"ticker": "BMW.DE",       "sector": "Autos",       "rating": "A",    "country": "DE"},
    "Daimler Truck":            {"ticker": "DTG.DE",       "sector": "Autos",       "rating": "BBB+", "country": "DE"},
    "Mercedes-Benz":            {"ticker": "MBG.DE",       "sector": "Autos",       "rating": "A-",   "country": "DE"},
    "Volvo":                    {"ticker": "VOLV-B.ST",    "sector": "Autos",       "rating": "A-",   "country": "SE"},
    "Continental":              {"ticker": "CON.DE",       "sector": "Autos",       "rating": "BBB",  "country": "DE"},

    # --- Telecoms ---
    "Deutsche Telekom":         {"ticker": "DTE.DE",       "sector": "Telecoms",    "rating": "BBB+", "country": "DE"},
    "Orange":                   {"ticker": "ORA.PA",       "sector": "Telecoms",    "rating": "BBB+", "country": "FR"},
    "Telefonica":               {"ticker": "TEF.MC",       "sector": "Telecoms",    "rating": "BBB",  "country": "ES"},
    "Vodafone":                 {"ticker": "VOD.L",        "sector": "Telecoms",    "rating": "BBB",  "country": "GB"},
    "BT Group":                 {"ticker": "BT-A.L",       "sector": "Telecoms",    "rating": "BBB",  "country": "GB"},
    "KPN":                      {"ticker": "KPN.AS",       "sector": "Telecoms",    "rating": "BBB",  "country": "NL"},
    "Swisscom":                 {"ticker": "SCMN.SW",      "sector": "Telecoms",    "rating": "A-",   "country": "CH"},
    "Telia":                    {"ticker": "TELIA.ST",     "sector": "Telecoms",    "rating": "BBB+", "country": "SE"},
    "Telenor":                  {"ticker": "TEL.OL",       "sector": "Telecoms",    "rating": "A-",   "country": "NO"},

    # --- Utilities ---
    "Enel":                     {"ticker": "ENEL.MI",      "sector": "Utilities",   "rating": "BBB+", "country": "IT"},
    "Iberdrola":                {"ticker": "IBE.MC",       "sector": "Utilities",   "rating": "BBB+", "country": "ES"},
    "Engie":                    {"ticker": "ENGI.PA",      "sector": "Utilities",   "rating": "BBB+", "country": "FR"},
    "E.ON":                     {"ticker": "EOAN.DE",      "sector": "Utilities",   "rating": "BBB+", "country": "DE"},
    "RWE":                      {"ticker": "RWE.DE",       "sector": "Utilities",   "rating": "BBB+", "country": "DE"},
    "EDP":                      {"ticker": "EDP.LS",       "sector": "Utilities",   "rating": "BBB",  "country": "PT"},
    "National Grid":            {"ticker": "NG.L",         "sector": "Utilities",   "rating": "BBB+", "country": "GB"},
    "SSE":                      {"ticker": "SSE.L",        "sector": "Utilities",   "rating": "BBB+", "country": "GB"},
    "Fortum":                   {"ticker": "FORTUM.HE",    "sector": "Utilities",   "rating": "BBB",  "country": "FI"},
    "Veolia":                   {"ticker": "VIE.PA",       "sector": "Utilities",   "rating": "BBB",  "country": "FR"},
    "Orsted":                   {"ticker": "ORSTED.CO",    "sector": "Utilities",   "rating": "BBB+", "country": "DK"},

    # --- Energy / Oil & Gas ---
    "Shell":                    {"ticker": "SHEL.L",       "sector": "Energy",      "rating": "A+",   "country": "GB"},
    "BP":                       {"ticker": "BP.L",         "sector": "Energy",      "rating": "A-",   "country": "GB"},
    "TotalEnergies":            {"ticker": "TTE.PA",       "sector": "Energy",      "rating": "A+",   "country": "FR"},
    "Eni":                      {"ticker": "ENI.MI",       "sector": "Energy",      "rating": "A-",   "country": "IT"},
    "Repsol":                   {"ticker": "REP.MC",       "sector": "Energy",      "rating": "BBB",  "country": "ES"},
    "Equinor":                  {"ticker": "EQNR.OL",     "sector": "Energy",      "rating": "AA-",  "country": "NO"},

    # --- Industrials ---
    "Siemens":                  {"ticker": "SIE.DE",       "sector": "Industrials", "rating": "A+",   "country": "DE"},
    "Schneider Electric":       {"ticker": "SU.PA",        "sector": "Industrials", "rating": "A-",   "country": "FR"},
    "ABB":                      {"ticker": "ABBN.SW",      "sector": "Industrials", "rating": "A",    "country": "CH"},
    "Siemens Energy":           {"ticker": "ENR.DE",       "sector": "Industrials", "rating": "BBB",  "country": "DE"},
    "Atlas Copco":              {"ticker": "ATCO-A.ST",    "sector": "Industrials", "rating": "A+",   "country": "SE"},
    "Sandvik":                  {"ticker": "SAND.ST",      "sector": "Industrials", "rating": "A-",   "country": "SE"},
    "SKF":                      {"ticker": "SKF-B.ST",     "sector": "Industrials", "rating": "BBB+", "country": "SE"},
    "Thales":                   {"ticker": "HO.PA",        "sector": "Industrials", "rating": "A-",   "country": "FR"},
    "BAE Systems":              {"ticker": "BA.L",         "sector": "Industrials", "rating": "BBB+", "country": "GB"},
    "Smiths Group":             {"ticker": "SMIN.L",       "sector": "Industrials", "rating": "BBB",  "country": "GB"},

    # --- Consumer Goods ---
    "Unilever":                 {"ticker": "ULVR.L",       "sector": "Consumer",    "rating": "A+",   "country": "GB"},
    "Nestle":                   {"ticker": "NESN.SW",      "sector": "Consumer",    "rating": "AA-",  "country": "CH"},
    "Danone":                   {"ticker": "BN.PA",        "sector": "Consumer",    "rating": "BBB+", "country": "FR"},
    "Pernod Ricard":            {"ticker": "RI.PA",        "sector": "Consumer",    "rating": "BBB+", "country": "FR"},
    "Diageo":                   {"ticker": "DGE.L",        "sector": "Consumer",    "rating": "A-",   "country": "GB"},
    "AB InBev":                 {"ticker": "ABI.BR",       "sector": "Consumer",    "rating": "BBB+", "country": "BE"},
    "Heineken":                 {"ticker": "HEIA.AS",      "sector": "Consumer",    "rating": "BBB+", "country": "NL"},
    "British American Tobacco": {"ticker": "BATS.L",       "sector": "Consumer",    "rating": "BBB+", "country": "GB"},
    "Imperial Brands":          {"ticker": "IMB.L",        "sector": "Consumer",    "rating": "BBB",  "country": "GB"},
    "Henkel":                   {"ticker": "HEN3.DE",      "sector": "Consumer",    "rating": "A-",   "country": "DE"},
    "Adidas":                   {"ticker": "ADS.DE",       "sector": "Consumer",    "rating": "A+",   "country": "DE"},
    "LVMH":                     {"ticker": "MC.PA",        "sector": "Consumer",    "rating": "A+",   "country": "FR"},
    "Kering":                   {"ticker": "KER.PA",       "sector": "Consumer",    "rating": "A-",   "country": "FR"},
    "Essity":                   {"ticker": "ESSITY-B.ST",  "sector": "Consumer",    "rating": "BBB+", "country": "SE"},

    # --- Healthcare / Pharma ---
    "Roche":                    {"ticker": "ROG.SW",       "sector": "Healthcare",  "rating": "AA",   "country": "CH"},
    "Novartis":                 {"ticker": "NOVN.SW",      "sector": "Healthcare",  "rating": "AA-",  "country": "CH"},
    "AstraZeneca":              {"ticker": "AZN.L",        "sector": "Healthcare",  "rating": "A",    "country": "GB"},
    "GSK":                      {"ticker": "GSK.L",        "sector": "Healthcare",  "rating": "A-",   "country": "GB"},
    "Sanofi":                   {"ticker": "SAN.PA",       "sector": "Healthcare",  "rating": "A+",   "country": "FR"},
    "Bayer":                    {"ticker": "BAYN.DE",      "sector": "Healthcare",  "rating": "BBB",  "country": "DE"},
    "Novo Nordisk":             {"ticker": "NOVO-B.CO",    "sector": "Healthcare",  "rating": "AA-",  "country": "DK"},
    "Fresenius":                {"ticker": "FRE.DE",       "sector": "Healthcare",  "rating": "BBB",  "country": "DE"},
    "Smith & Nephew":           {"ticker": "SN.L",         "sector": "Healthcare",  "rating": "BBB",  "country": "GB"},

    # --- Chemicals ---
    "BASF":                     {"ticker": "BAS.DE",       "sector": "Chemicals",   "rating": "A",    "country": "DE"},
    "Linde":                    {"ticker": "LIN.DE",       "sector": "Chemicals",   "rating": "A+",   "country": "DE"},
    "Air Liquide":              {"ticker": "AI.PA",        "sector": "Chemicals",   "rating": "A+",   "country": "FR"},
    "Akzo Nobel":               {"ticker": "AKZA.AS",      "sector": "Chemicals",   "rating": "BBB+", "country": "NL"},
    "Solvay":                   {"ticker": "SOLB.BR",      "sector": "Chemicals",   "rating": "BBB",  "country": "BE"},
    "DSM-Firmenich":            {"ticker": "DSFIR.AS",     "sector": "Chemicals",   "rating": "BBB+", "country": "NL"},
    "Evonik":                   {"ticker": "EVK.DE",       "sector": "Chemicals",   "rating": "BBB",  "country": "DE"},

    # --- Technology ---
    "SAP":                      {"ticker": "SAP.DE",       "sector": "Technology",  "rating": "A",    "country": "DE"},
    "ASML":                     {"ticker": "ASML.AS",      "sector": "Technology",  "rating": "A+",   "country": "NL"},
    "Nokia":                    {"ticker": "NOKIA.HE",     "sector": "Technology",  "rating": "BBB-", "country": "FI"},
    "Ericsson":                 {"ticker": "ERIC-B.ST",    "sector": "Technology",  "rating": "BBB-", "country": "SE"},

    # --- Real Estate ---
    "Vonovia":                  {"ticker": "VNA.DE",       "sector": "Real Estate", "rating": "BBB+", "country": "DE"},
    "Unibail-Rodamco":          {"ticker": "URW.AS",       "sector": "Real Estate", "rating": "BBB+", "country": "FR"},
    "British Land":             {"ticker": "BLND.L",       "sector": "Real Estate", "rating": "A-",   "country": "GB"},
    "Land Securities":          {"ticker": "LAND.L",       "sector": "Real Estate", "rating": "A-",   "country": "GB"},

    # --- Retail / Distribution ---
    "Tesco":                    {"ticker": "TSCO.L",       "sector": "Retail",      "rating": "BBB",  "country": "GB"},
    "Carrefour":                {"ticker": "CA.PA",        "sector": "Retail",      "rating": "BBB",  "country": "FR"},
    "Ahold Delhaize":           {"ticker": "AD.AS",        "sector": "Retail",      "rating": "BBB+", "country": "NL"},

    # --- Media / Entertainment ---
    "WPP":                      {"ticker": "WPP.L",        "sector": "Media",       "rating": "BBB",  "country": "GB"},
    "Pearson":                  {"ticker": "PSON.L",       "sector": "Media",       "rating": "BBB",  "country": "GB"},
    "Publicis":                 {"ticker": "PUB.PA",       "sector": "Media",       "rating": "BBB+", "country": "FR"},

    # --- Mining / Materials ---
    "Anglo American":           {"ticker": "AAL.L",        "sector": "Mining",      "rating": "BBB",  "country": "GB"},
    "Glencore":                 {"ticker": "GLEN.L",       "sector": "Mining",      "rating": "BBB+", "country": "CH"},
    "Rio Tinto":                {"ticker": "RIO.L",        "sector": "Mining",      "rating": "A",    "country": "GB"},
    "CRH":                      {"ticker": "CRH.L",        "sector": "Building",    "rating": "BBB+", "country": "IE"},
    "Saint-Gobain":             {"ticker": "SGO.PA",       "sector": "Building",    "rating": "BBB",  "country": "FR"},
    "LafargeHolcim":            {"ticker": "LHN.SW",       "sector": "Building",    "rating": "BBB",  "country": "CH"},

    # --- Transport / Logistics ---
    "Maersk":                   {"ticker": "MAERSK-B.CO",  "sector": "Transport",   "rating": "BBB+", "country": "DK"},
    "Deutsche Post DHL":        {"ticker": "DHL.DE",       "sector": "Transport",   "rating": "BBB+", "country": "DE"},
    "DSV Panalpina":            {"ticker": "DSV.CO",       "sector": "Transport",   "rating": "A-",   "country": "DK"},

    # --- Paper / Packaging ---
    "UPM-Kymmene":              {"ticker": "UPM.HE",       "sector": "Paper",       "rating": "BBB",  "country": "FI"},
    "Stora Enso":               {"ticker": "STERV.HE",     "sector": "Paper",       "rating": "BBB",  "country": "FI"},
    "Mondi":                    {"ticker": "MNDI.L",       "sector": "Paper",       "rating": "BBB",  "country": "GB"},

    # --- Food / Beverages ---
    "Associated British Foods": {"ticker": "ABF.L",        "sector": "Food",        "rating": "BBB+", "country": "GB"},
    "Kerry Group":              {"ticker": "KYG.L",        "sector": "Food",        "rating": "BBB+", "country": "IE"},
    "Jeronimo Martins":         {"ticker": "JMT.LS",       "sector": "Food",        "rating": "BBB", "country": "PT"},
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MainConstituentData:
    """Holds fetched data for a single iTraxx Main constituent."""
    name: str
    ticker: str
    sector: str
    rating: str
    country: str
    prices: Optional[pd.Series] = None
    market_cap: float = 0.0
    total_debt: float = 0.0
    shares_outstanding: float = 0.0
    currency: str = ""
    fetch_success: bool = False
    error_msg: str = ""

    # --- Fundamental Financial Data (annual, up to 4yr series, in $M) ---
    total_revenue: Optional[pd.Series] = None
    ebitda: Optional[pd.Series] = None
    operating_income: Optional[pd.Series] = None
    interest_expense: Optional[pd.Series] = None
    net_income: Optional[pd.Series] = None
    cash: Optional[pd.Series] = None
    current_liabilities: Optional[pd.Series] = None
    total_assets: Optional[pd.Series] = None
    stockholders_equity: Optional[pd.Series] = None
    operating_cash_flow: Optional[pd.Series] = None
    free_cash_flow: Optional[pd.Series] = None
    capex: Optional[pd.Series] = None
    depreciation: Optional[pd.Series] = None

    # --- Latest Snapshot Scalars ---
    ebitda_latest: float = 0.0
    ebitda_margin: float = 0.0
    operating_margin: float = 0.0
    free_cashflow_latest: float = 0.0
    operating_cashflow_latest: float = 0.0
    current_ratio: float = 0.0
    debt_to_equity: float = 0.0
    enterprise_value: float = 0.0

    has_fundamentals: bool = False


# =============================================================================
# CACHING
# =============================================================================

def _cache_path():
    """Return path for today's cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"main_constituents_{datetime.now().strftime('%Y%m%d')}.json")


def load_cache() -> Optional[dict]:
    """Load cached data if it exists and is fresh enough."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_files = sorted(glob.glob(os.path.join(CACHE_DIR, "main_constituents_*.json")), reverse=True)
    if not cache_files:
        return None
    latest = cache_files[0]
    mtime = datetime.fromtimestamp(os.path.getmtime(latest))
    age_hours = (datetime.now() - mtime).total_seconds() / 3600
    if age_hours > CACHE_MAX_AGE_HOURS:
        return None
    try:
        with open(latest, "r") as f:
            return json.load(f)
    except Exception:
        return None


_FUNDAMENTAL_SERIES_FIELDS = [
    "total_revenue", "ebitda", "operating_income", "interest_expense", "net_income",
    "cash", "current_liabilities", "total_assets", "stockholders_equity",
    "operating_cash_flow", "free_cash_flow", "capex", "depreciation",
]

_FUNDAMENTAL_SCALAR_FIELDS = [
    "ebitda_latest", "ebitda_margin", "operating_margin",
    "free_cashflow_latest", "operating_cashflow_latest",
    "current_ratio", "debt_to_equity", "enterprise_value",
]


def _series_to_dict(s: Optional[pd.Series]) -> dict:
    """Convert pd.Series to JSON-safe dict."""
    if s is None or len(s) == 0:
        return {}
    return {d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d): float(v)
            for d, v in s.items() if pd.notna(v)}


def _dict_to_series(d: dict) -> Optional[pd.Series]:
    """Reconstruct pd.Series from dict."""
    if not d:
        return None
    idx = pd.to_datetime(list(d.keys()))
    vals = list(d.values())
    return pd.Series(vals, index=idx).sort_index()


def save_cache(constituents: List[MainConstituentData]):
    """Save fetched data to JSON cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    records = []
    for c in constituents:
        rec = {
            "name": c.name, "ticker": c.ticker, "sector": c.sector,
            "rating": c.rating, "country": c.country,
            "market_cap": c.market_cap, "total_debt": c.total_debt,
            "shares_outstanding": c.shares_outstanding, "currency": c.currency,
            "fetch_success": c.fetch_success, "error_msg": c.error_msg,
        }
        if c.prices is not None and len(c.prices) > 0:
            rec["prices"] = {d.strftime("%Y-%m-%d"): float(v) for d, v in c.prices.items()}
        else:
            rec["prices"] = {}
        for fld in _FUNDAMENTAL_SERIES_FIELDS:
            rec[fld] = _series_to_dict(getattr(c, fld, None))
        for fld in _FUNDAMENTAL_SCALAR_FIELDS:
            rec[fld] = getattr(c, fld, 0.0)
        rec["has_fundamentals"] = c.has_fundamentals
        records.append(rec)

    with open(_cache_path(), "w") as f:
        json.dump(records, f, indent=1)


def _reconstruct_from_cache(cache_data: list) -> List[MainConstituentData]:
    """Rebuild MainConstituentData objects from cached JSON."""
    result = []
    for rec in cache_data:
        prices = None
        if rec.get("prices"):
            idx = pd.to_datetime(list(rec["prices"].keys()))
            vals = list(rec["prices"].values())
            prices = pd.Series(vals, index=idx, name="Close").sort_index()

        cd = MainConstituentData(
            name=rec["name"], ticker=rec["ticker"], sector=rec["sector"],
            rating=rec["rating"], country=rec["country"],
            prices=prices,
            market_cap=rec.get("market_cap", 0),
            total_debt=rec.get("total_debt", 0),
            shares_outstanding=rec.get("shares_outstanding", 0),
            currency=rec.get("currency", ""),
            fetch_success=rec.get("fetch_success", False),
            error_msg=rec.get("error_msg", ""),
        )
        for fld in _FUNDAMENTAL_SERIES_FIELDS:
            setattr(cd, fld, _dict_to_series(rec.get(fld, {})))
        for fld in _FUNDAMENTAL_SCALAR_FIELDS:
            setattr(cd, fld, rec.get(fld, 0.0))
        cd.has_fundamentals = rec.get("has_fundamentals", False)
        result.append(cd)
    return result


# =============================================================================
# DATA FETCHING
# =============================================================================

def _extract_series(df, row_names: list, scale: float = 1e-6) -> Optional[pd.Series]:
    """Extract a row from a yfinance financial statement DataFrame as Series in $M."""
    if df is None or df.empty:
        return None
    for name in row_names:
        if name in df.index:
            row = df.loc[name].dropna()
            if len(row) > 0:
                vals = row.astype(float) * scale
                return vals.sort_index()
    return None


def _fetch_fundamentals(tk, base: MainConstituentData):
    """Fetch income statement, balance sheet, cash flow from yfinance."""
    try:
        inc = tk.financials
        if inc is not None and not inc.empty:
            base.total_revenue = _extract_series(inc, ["Total Revenue", "Revenue"])
            base.ebitda = _extract_series(inc, ["EBITDA", "Normalized EBITDA"])
            base.operating_income = _extract_series(inc, ["Operating Income", "EBIT"])
            base.interest_expense = _extract_series(inc, ["Interest Expense", "Interest Expense Non Operating"])
            base.net_income = _extract_series(inc, ["Net Income", "Net Income Common Stockholders"])
    except Exception:
        pass

    try:
        bs = tk.balance_sheet
        if bs is not None and not bs.empty:
            base.cash = _extract_series(bs, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
            base.current_liabilities = _extract_series(bs, ["Current Liabilities", "Total Current Liabilities"])
            base.total_assets = _extract_series(bs, ["Total Assets"])
            base.stockholders_equity = _extract_series(bs, ["Stockholders Equity", "Total Equity Gross Minority Interest"])
    except Exception:
        pass

    try:
        cf = tk.cashflow
        if cf is not None and not cf.empty:
            base.operating_cash_flow = _extract_series(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
            base.free_cash_flow = _extract_series(cf, ["Free Cash Flow", "Levered Free Cash Flow"])
            base.capex = _extract_series(cf, ["Capital Expenditure", "Purchase Of PPE"])
            base.depreciation = _extract_series(cf, ["Depreciation And Amortization", "Depreciation Amortization Depletion"])
    except Exception:
        pass

    try:
        yf_info = tk.info or {}
        base.ebitda_latest = (yf_info.get("ebitda") or 0) / 1e6
        base.ebitda_margin = yf_info.get("ebitdaMargins") or 0.0
        base.operating_margin = yf_info.get("operatingMargins") or 0.0
        base.free_cashflow_latest = (yf_info.get("freeCashflow") or 0) / 1e6
        base.operating_cashflow_latest = (yf_info.get("operatingCashflow") or 0) / 1e6
        base.current_ratio = yf_info.get("currentRatio") or 0.0
        base.debt_to_equity = yf_info.get("debtToEquity") or 0.0
        base.enterprise_value = (yf_info.get("enterpriseValue") or 0) / 1e6
    except Exception:
        pass

    has_any = any([
        base.total_revenue is not None,
        base.ebitda is not None,
        base.operating_cash_flow is not None,
        base.ebitda_latest != 0,
    ])
    base.has_fundamentals = has_any


def fetch_single_main_constituent(name: str, info: dict, period: str = "2y") -> MainConstituentData:
    """Fetch a single constituent's equity data from Yahoo Finance."""
    ticker_str = info["ticker"]
    base = MainConstituentData(
        name=name, ticker=ticker_str, sector=info["sector"],
        rating=info["rating"], country=info["country"],
    )
    try:
        tk = yf.Ticker(ticker_str)
        hist = tk.history(period=period, auto_adjust=True)
        if hist.empty or len(hist) < 10:
            base.error_msg = "No/insufficient price data"
            return base

        prices = hist["Close"].dropna()
        base.prices = prices

        yf_info = tk.info or {}
        base.market_cap = yf_info.get("marketCap", 0) / 1e6 if yf_info.get("marketCap") else 0
        base.total_debt = yf_info.get("totalDebt", 0) / 1e6 if yf_info.get("totalDebt") else 0
        base.shares_outstanding = yf_info.get("sharesOutstanding", 0)
        base.currency = yf_info.get("currency", "")

        if base.total_debt == 0:
            try:
                bs = tk.balance_sheet
                if bs is not None and not bs.empty:
                    for col_name in ["Total Debt", "Long Term Debt", "Total Liabilities Net Minority Interest"]:
                        if col_name in bs.index:
                            val = bs.loc[col_name].iloc[0]
                            if pd.notna(val) and val > 0:
                                base.total_debt = float(val) / 1e6
                                break
            except Exception:
                pass

        base.fetch_success = True

        try:
            _fetch_fundamentals(tk, base)
        except Exception:
            pass

        return base

    except Exception as e:
        base.error_msg = str(e)[:100]
        return base


def fetch_all_main_constituents(period: str = "2y", use_cache: bool = True) -> List[MainConstituentData]:
    """
    Fetch equity data for all iTraxx Main constituents.
    Uses JSON cache if available and fresh (<24h).
    """
    if use_cache:
        cached = load_cache()
        if cached is not None:
            print("=" * 70)
            print("  LOADED FROM CACHE (< 24h old)")
            print("=" * 70)
            result = _reconstruct_from_cache(cached)
            ok = sum(1 for c in result if c.fetch_success)
            fail = sum(1 for c in result if not c.fetch_success)
            print(f"  {ok} fetched OK, {fail} failed")
            return result

    print("=" * 70)
    print("  FETCHING iTRAXX MAIN CONSTITUENTS FROM YAHOO FINANCE")
    print("=" * 70)
    print(f"  {len(MAIN_CONSTITUENTS)} names | Period: {period}")
    print()

    results = []
    for i, (name, info) in enumerate(MAIN_CONSTITUENTS.items()):
        c = fetch_single_main_constituent(name, info, period=period)
        results.append(c)

        if c.fetch_success:
            n_prices = len(c.prices) if c.prices is not None else 0
            latest_price = f"{c.prices.iloc[-1]:.2f}" if c.prices is not None and len(c.prices) > 0 else "N/A"
            mcap_str = f"MCap={c.market_cap:,.0f}M" if c.market_cap > 0 else "MCap=N/A"
            debt_str = f"Debt={c.total_debt:,.0f}M" if c.total_debt > 0 else "Debt=N/A"
            fund_str = "FND=Y" if c.has_fundamentals else "FND=N"
            print(f"  [{i+1:3d}/{len(MAIN_CONSTITUENTS)}] [OK]   {name:30s} | {info['ticker']:15s} | "
                  f"Price={latest_price:>10s} | {mcap_str} | {debt_str} | {fund_str} | {n_prices} days")
        else:
            print(f"  [{i+1:3d}/{len(MAIN_CONSTITUENTS)}] [FAIL] {name:30s} | {info['ticker']:15s} | {c.error_msg}")

        time.sleep(FETCH_DELAY_SEC)

    ok = sum(1 for c in results if c.fetch_success)
    fail = sum(1 for c in results if not c.fetch_success)
    n_fund = sum(1 for c in results if c.has_fundamentals)
    print(f"\n  Total: {ok} OK, {fail} failed out of {len(MAIN_CONSTITUENTS)}")
    print(f"  Fundamentals: {n_fund} names with financial statement data")

    save_cache(results)
    print(f"  Cache saved: {_cache_path()}")

    return results


# =============================================================================
# EQUITY METRIC COMPUTATION
# =============================================================================

def compute_equity_metrics(constituents: List[MainConstituentData]) -> pd.DataFrame:
    """
    Compute equity-based metrics for all successfully fetched constituents.
    Returns DataFrame with columns:
      name, ticker, sector, rating, country, currency, price,
      vol_252d, vol_63d, vol_21d, vol_regime,
      momentum_63d, momentum_126d, drawdown_52w,
      market_cap_mm, total_debt_mm, leverage_ratio, mcap_change_63d
    """
    rows = []
    for c in constituents:
        if not c.fetch_success or c.prices is None or len(c.prices) < 63:
            continue

        prices = c.prices.sort_index()
        returns = prices.pct_change().dropna()

        vol_252d = returns.tail(252).std() * np.sqrt(252) * 100 if len(returns) >= 252 else (
            returns.std() * np.sqrt(252) * 100
        )
        vol_63d = returns.tail(63).std() * np.sqrt(252) * 100
        vol_21d = returns.tail(21).std() * np.sqrt(252) * 100

        if len(returns) >= 252:
            vol_ratio = vol_21d / vol_252d if vol_252d > 0 else 1.0
        else:
            vol_ratio = 1.0

        if vol_21d > 50:
            vol_regime = "CRISIS"
        elif vol_ratio > 1.5:
            vol_regime = "CRISIS"
        elif vol_ratio > 1.0:
            vol_regime = "ELEVATED"
        elif vol_ratio > 0.7:
            vol_regime = "NORMAL"
        else:
            vol_regime = "LOW"

        momentum_63d = (prices.iloc[-1] / prices.iloc[-63] - 1) * 100 if len(prices) >= 63 else np.nan
        momentum_126d = (prices.iloc[-1] / prices.iloc[-126] - 1) * 100 if len(prices) >= 126 else np.nan

        lookback = min(252, len(prices))
        high_52w = prices.tail(lookback).max()
        drawdown_52w = (prices.iloc[-1] / high_52w - 1) * 100

        leverage_ratio = c.total_debt / c.market_cap if c.market_cap > 0 else np.nan
        mcap_change_63d = (prices.iloc[-1] / prices.iloc[-63] - 1) * 100 if len(prices) >= 63 else np.nan

        rows.append({
            "name": c.name,
            "ticker": c.ticker,
            "sector": c.sector,
            "rating": c.rating,
            "country": c.country,
            "currency": c.currency,
            "price": round(prices.iloc[-1], 2),
            "vol_252d": round(vol_252d, 1),
            "vol_63d": round(vol_63d, 1),
            "vol_21d": round(vol_21d, 1),
            "vol_regime": vol_regime,
            "momentum_63d": round(momentum_63d, 1) if not pd.isna(momentum_63d) else np.nan,
            "momentum_126d": round(momentum_126d, 1) if not pd.isna(momentum_126d) else np.nan,
            "drawdown_52w": round(drawdown_52w, 1),
            "market_cap_mm": round(c.market_cap, 0),
            "total_debt_mm": round(c.total_debt, 0),
            "leverage_ratio": round(leverage_ratio, 2) if not pd.isna(leverage_ratio) else np.nan,
            "mcap_change_63d": round(mcap_change_63d, 1) if not pd.isna(mcap_change_63d) else np.nan,
        })

    return pd.DataFrame(rows)


# =============================================================================
# CONSOLE OUTPUT
# =============================================================================

def print_report(metrics_df: pd.DataFrame, failed: List[str]):
    """Print formatted constituent metrics report."""
    print("\n" + "=" * 110)
    print("  iTRAXX MAIN CONSTITUENT ANALYSIS - EQUITY METRICS")
    print("=" * 110)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Constituents analysed: {len(metrics_df)}")
    if failed:
        print(f"  Failed tickers ({len(failed)}): {', '.join(failed[:10])}")

    # 1. Main table
    print(f"\n{'=' * 110}")
    print("  1. FULL CONSTITUENT TABLE")
    print(f"{'=' * 110}")
    print(f"  {'Name':<28s} {'Sector':<15s} {'Rating':>6s} {'Price':>8s} "
          f"{'Vol21d':>7s} {'Vol63d':>7s} {'Mom63d':>8s} {'DD52w':>7s} "
          f"{'Leverage':>9s} {'MCap$M':>10s}")
    print("  " + "-" * 106)

    for _, row in metrics_df.iterrows():
        lev = f"{row['leverage_ratio']:.2f}" if pd.notna(row['leverage_ratio']) else "N/A"
        mom = f"{row['momentum_63d']:+.1f}%" if pd.notna(row['momentum_63d']) else "N/A"
        dd = f"{row['drawdown_52w']:.1f}%" if pd.notna(row['drawdown_52w']) else "N/A"
        print(f"  {row['name']:<28s} {row['sector']:<15s} {row['rating']:>6s} "
              f"{row['price']:>8.2f} {row['vol_21d']:>6.1f}% {row['vol_63d']:>6.1f}% "
              f"{mom:>8s} {dd:>7s} {lev:>9s} {row['market_cap_mm']:>10,.0f}")

    # 2. Worst drawdowns
    print(f"\n{'=' * 110}")
    print("  2. TOP 10 WORST DRAWDOWNS (from 52-week high)")
    print(f"{'=' * 110}")
    worst_dd = metrics_df.nsmallest(10, "drawdown_52w")
    for _, row in worst_dd.iterrows():
        print(f"  {row['name']:<30s} {row['sector']:<15s} {row['drawdown_52w']:>+7.1f}% "
              f"(Vol21d: {row['vol_21d']:.1f}%)")

    # 3. Highest leverage
    lev_valid = metrics_df.dropna(subset=["leverage_ratio"])
    if len(lev_valid) > 0:
        print(f"\n{'=' * 110}")
        print("  3. TOP 10 HIGHEST LEVERAGE (Debt/MCap)")
        print(f"{'=' * 110}")
        worst_lev = lev_valid.nlargest(10, "leverage_ratio")
        for _, row in worst_lev.iterrows():
            print(f"  {row['name']:<30s} {row['sector']:<15s} Leverage: {row['leverage_ratio']:.2f}x "
                  f"(Debt: ${row['total_debt_mm']:,.0f}M / MCap: ${row['market_cap_mm']:,.0f}M)")

    # 4. Highest vol
    print(f"\n{'=' * 110}")
    print("  4. TOP 10 HIGHEST VOLATILITY (21-day)")
    print(f"{'=' * 110}")
    worst_vol = metrics_df.nlargest(10, "vol_21d")
    for _, row in worst_vol.iterrows():
        print(f"  {row['name']:<30s} {row['sector']:<15s} Vol21d: {row['vol_21d']:.1f}% "
              f"(Regime: {row['vol_regime']})")

    # 5. Sector summary
    print(f"\n{'=' * 110}")
    print("  5. SECTOR SUMMARY")
    print(f"{'=' * 110}")
    sector_grp = metrics_df.groupby("sector").agg({
        "name": "count",
        "vol_21d": "mean",
        "drawdown_52w": "mean",
        "leverage_ratio": "mean",
        "momentum_63d": "mean",
    }).rename(columns={"name": "count"}).sort_values("drawdown_52w")

    print(f"  {'Sector':<20s} {'Count':>5s} {'Avg Vol':>8s} {'Avg DD':>8s} {'Avg Lev':>8s} {'Avg Mom':>8s}")
    print("  " + "-" * 60)
    for sector, row in sector_grp.iterrows():
        lev_str = f"{row['leverage_ratio']:.2f}" if pd.notna(row['leverage_ratio']) else "N/A"
        mom_str = f"{row['momentum_63d']:+.1f}%" if pd.notna(row['momentum_63d']) else "N/A"
        print(f"  {sector:<20s} {int(row['count']):>5d} {row['vol_21d']:>7.1f}% "
              f"{row['drawdown_52w']:>+7.1f}% {lev_str:>8s} {mom_str:>8s}")

    # 6. Rating distribution
    print(f"\n{'=' * 110}")
    print("  6. RATING DISTRIBUTION")
    print(f"{'=' * 110}")
    rating_order = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]
    rating_counts = metrics_df["rating"].value_counts()
    for r in rating_order:
        cnt = rating_counts.get(r, 0)
        if cnt > 0:
            bar = "*" * cnt
            print(f"  {r:>5s}: {cnt:>3d} {bar}")

    print("\n" + "=" * 110)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(metrics_df: pd.DataFrame):
    """Create constituent dashboard visualization."""
    if len(metrics_df) == 0:
        print("  No data to plot.")
        return

    fig = plt.figure(figsize=(24, 18))
    fig.suptitle(
        "iTRAXX MAIN CONSTITUENTS - EQUITY METRICS DASHBOARD",
        fontsize=18, fontweight="bold", y=0.98,
    )
    fig.text(
        0.5, 0.955,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Data: Yahoo Finance | {len(metrics_df)} names",
        ha="center", fontsize=10, color="gray",
    )

    gs = gridspec.GridSpec(3, 3, hspace=0.4, wspace=0.35, top=0.93, bottom=0.04)

    # --- Panel 1: Leverage Ratios (sorted) ---
    ax1 = fig.add_subplot(gs[0, :2])
    lev_data = metrics_df.dropna(subset=["leverage_ratio"]).sort_values("leverage_ratio", ascending=True)
    if len(lev_data) > 0:
        colors = []
        for lev in lev_data["leverage_ratio"]:
            if lev > 2.0:
                colors.append("#e74c3c")
            elif lev > 1.0:
                colors.append("#f39c12")
            else:
                colors.append("#2ecc71")
        ax1.barh(range(len(lev_data)), lev_data["leverage_ratio"].values, color=colors, edgecolor="white", linewidth=0.3)
        ax1.set_yticks(range(len(lev_data)))
        ax1.set_yticklabels([n[:18] for n in lev_data["name"]], fontsize=5)
        ax1.axvline(1.0, color="orange", linewidth=0.8, linestyle="--", label="1.0x")
        ax1.axvline(2.0, color="red", linewidth=0.8, linestyle="--", label="2.0x")
        ax1.set_title("Leverage Ratio (Debt / Market Cap)", fontweight="bold")
        ax1.set_xlabel("Leverage")
        ax1.legend(fontsize=7)
        ax1.grid(True, alpha=0.3, axis="x")

    # --- Panel 2: Summary Box ---
    ax_sum = fig.add_subplot(gs[0, 2])
    ax_sum.set_xlim(0, 1)
    ax_sum.set_ylim(0, 1)
    ax_sum.axis("off")

    n_crisis = len(metrics_df[metrics_df["vol_regime"] == "CRISIS"])
    n_elevated = len(metrics_df[metrics_df["vol_regime"] == "ELEVATED"])
    avg_dd = metrics_df["drawdown_52w"].mean()
    avg_lev = metrics_df["leverage_ratio"].mean()
    avg_mom = metrics_df["momentum_63d"].mean()

    box = FancyBboxPatch((0.05, 0.1), 0.9, 0.8, boxstyle="round,pad=0.05",
                          facecolor="#2c3e50", alpha=0.15, edgecolor="#2c3e50", linewidth=2)
    ax_sum.add_patch(box)
    ax_sum.text(0.5, 0.88, "UNIVERSE SUMMARY", ha="center", fontsize=12, fontweight="bold")
    ax_sum.text(0.5, 0.76, f"Names: {len(metrics_df)}", ha="center", fontsize=10)
    ax_sum.text(0.5, 0.65, f"Index: iTraxx Main (IG)", ha="center", fontsize=9, color="#3498db")
    ax_sum.text(0.5, 0.54, f"Crisis Vol: {n_crisis}  |  Elevated Vol: {n_elevated}", ha="center", fontsize=9,
                color="#e74c3c" if n_crisis > 3 else "#f39c12" if n_elevated > 5 else "#2ecc71")
    ax_sum.text(0.5, 0.43, f"Avg Drawdown: {avg_dd:+.1f}%", ha="center", fontsize=10,
                color="#e74c3c" if avg_dd < -15 else "#f39c12" if avg_dd < -5 else "#2ecc71")
    ax_sum.text(0.5, 0.32, f"Avg Leverage: {avg_lev:.2f}x" if pd.notna(avg_lev) else "Avg Leverage: N/A",
                ha="center", fontsize=10)
    ax_sum.text(0.5, 0.21, f"Avg 63d Momentum: {avg_mom:+.1f}%" if pd.notna(avg_mom) else "Avg Mom: N/A",
                ha="center", fontsize=10,
                color="#2ecc71" if pd.notna(avg_mom) and avg_mom > 0 else "#e74c3c")

    # --- Panel 3: Drawdowns (sorted) ---
    ax2 = fig.add_subplot(gs[1, :2])
    dd_data = metrics_df.sort_values("drawdown_52w", ascending=True)
    colors_dd = ["#e74c3c" if d < -30 else "#f39c12" if d < -15 else "#95a5a6" if d < -5 else "#2ecc71"
                 for d in dd_data["drawdown_52w"]]
    ax2.barh(range(len(dd_data)), dd_data["drawdown_52w"].values, color=colors_dd, edgecolor="white", linewidth=0.3)
    ax2.set_yticks(range(len(dd_data)))
    ax2.set_yticklabels([n[:18] for n in dd_data["name"]], fontsize=5)
    ax2.axvline(0, color="black", linewidth=0.8)
    ax2.axvline(-15, color="orange", linewidth=0.8, linestyle="--")
    ax2.axvline(-30, color="red", linewidth=0.8, linestyle="--")
    ax2.set_title("Drawdown from 52-Week High (%)", fontweight="bold")
    ax2.set_xlabel("Drawdown %")
    ax2.grid(True, alpha=0.3, axis="x")

    # --- Panel 4: Vol vs Leverage Scatter ---
    ax3 = fig.add_subplot(gs[1, 2])
    scatter_df = metrics_df.dropna(subset=["leverage_ratio", "vol_63d"])
    if len(scatter_df) > 0:
        sector_colors = {}
        all_sectors = sorted(scatter_df["sector"].unique())
        cmap = plt.cm.Set3(np.linspace(0, 1, max(len(all_sectors), 1)))
        for i, s in enumerate(all_sectors):
            sector_colors[s] = cmap[i]

        for _, row in scatter_df.iterrows():
            size = max(20, min(200, row["market_cap_mm"] / 500))
            ax3.scatter(row["leverage_ratio"], row["vol_63d"], s=size,
                       c=[sector_colors.get(row["sector"], "gray")], alpha=0.7, edgecolor="white", linewidth=0.5)

        ax3.set_xlabel("Leverage Ratio (Debt/MCap)")
        ax3.set_ylabel("63d Realized Vol (%)")
        ax3.set_title("Vol vs Leverage (size = MCap)", fontweight="bold", fontsize=10)
        ax3.axhline(35, color="orange", linewidth=0.7, linestyle="--")
        ax3.axvline(1.5, color="orange", linewidth=0.7, linestyle="--")
        ax3.grid(True, alpha=0.3)

    # --- Panel 5: Sector Average Metrics Heatmap ---
    ax4 = fig.add_subplot(gs[2, :2])
    sector_agg = metrics_df.groupby("sector").agg({
        "vol_21d": "mean", "drawdown_52w": "mean",
        "leverage_ratio": "mean", "momentum_63d": "mean", "name": "count",
    }).rename(columns={"name": "count"}).sort_values("drawdown_52w")

    if len(sector_agg) > 0:
        display_cols = ["vol_21d", "drawdown_52w", "leverage_ratio", "momentum_63d"]
        available_cols = [c for c in display_cols if c in sector_agg.columns]
        heatmap_data = sector_agg[available_cols].copy()

        for col in available_cols:
            col_vals = heatmap_data[col].dropna()
            if len(col_vals) > 0 and col_vals.max() != col_vals.min():
                heatmap_data[col] = (heatmap_data[col] - col_vals.min()) / (col_vals.max() - col_vals.min())
            else:
                heatmap_data[col] = 0.5

        im = ax4.imshow(heatmap_data.values, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=1)
        ax4.set_yticks(range(len(heatmap_data)))
        ax4.set_yticklabels(heatmap_data.index, fontsize=7)
        col_labels = ["Vol 21d", "Drawdown", "Leverage", "Momentum"]
        ax4.set_xticks(range(len(available_cols)))
        ax4.set_xticklabels(col_labels[:len(available_cols)], fontsize=8)
        ax4.set_title("Sector Heatmap (red = worse, green = better)", fontweight="bold", fontsize=10)

        for i, sector in enumerate(sector_agg.index):
            for j, col in enumerate(available_cols):
                val = sector_agg.loc[sector, col]
                if pd.notna(val):
                    txt = f"{val:.1f}" if col != "leverage_ratio" else f"{val:.2f}"
                    ax4.text(j, i, txt, ha="center", va="center", fontsize=7, color="black")

    # --- Panel 6: Rating Distribution ---
    ax5 = fig.add_subplot(gs[2, 2])
    rating_order = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]
    rating_counts = metrics_df["rating"].value_counts()
    rating_sorted = pd.Series(index=rating_order, dtype=int)
    for r in rating_order:
        rating_sorted[r] = rating_counts.get(r, 0)
    rating_sorted = rating_sorted[rating_sorted > 0]

    if len(rating_sorted) > 0:
        rating_colors = {"AAA": "#1a5276", "AA+": "#1f618d", "AA": "#2471a3", "AA-": "#2980b9",
                         "A+": "#2ecc71", "A": "#27ae60", "A-": "#229954",
                         "BBB+": "#f1c40f", "BBB": "#f39c12", "BBB-": "#e67e22"}
        colors_r = [rating_colors.get(r, "#95a5a6") for r in rating_sorted.index]
        ax5.bar(range(len(rating_sorted)), rating_sorted.values, color=colors_r, edgecolor="white")
        ax5.set_xticks(range(len(rating_sorted)))
        ax5.set_xticklabels(rating_sorted.index, fontsize=8, rotation=45)
        ax5.set_ylabel("Count")
        ax5.set_title("Rating Distribution (IG)", fontweight="bold", fontsize=10)
        ax5.grid(True, alpha=0.3, axis="y")

    plt.savefig("itraxx_main_constituents_dashboard.png", dpi=150, bbox_inches="tight")
    print(f"\n  Chart saved: itraxx_main_constituents_dashboard.png")
    plt.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 70)
    print("  iTRAXX MAIN CONSTITUENT DATA LAYER")
    print("  125 Investment Grade names - Equity data via Yahoo Finance")
    print("=" * 70)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Constituents: {len(MAIN_CONSTITUENTS)}")
    print(f"  History: {HISTORY_PERIOD}")
    print()

    # 1. Fetch data
    constituents = fetch_all_main_constituents(period=HISTORY_PERIOD, use_cache=True)

    # 2. Compute metrics
    success = [c for c in constituents if c.fetch_success]
    failed = [c.name for c in constituents if not c.fetch_success]
    print(f"\n  Computing equity metrics for {len(success)} names...")
    metrics_df = compute_equity_metrics(success)

    # 3. Report
    print_report(metrics_df, failed)

    # 4. Dashboard
    print("\n  Generating dashboard chart...")
    plot_dashboard(metrics_df)

    # 5. Save CSV
    if len(metrics_df) > 0:
        metrics_df.to_csv("itraxx_main_constituents_metrics.csv", index=False)
        print(f"  Metrics saved: itraxx_main_constituents_metrics.csv")

    print("\n  DONE.\n")


if __name__ == "__main__":
    main()
