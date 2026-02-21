"""
Credit-Equity Options Bridge -- The Alpha Engine

Orchestrates the CDS-equity gap detection pipeline:
  1. Loads credit data (spreads, RV scores, filings, maturity risk)
  2. Loads equity data (prices, IV, options chain) via yfinance
  3. Scores each name with signal_scorer
  4. Recommends trade structures via trade_structurer
  5. Returns ranked opportunities sorted by gap score

Usage:
    python -m analytics.credit_equity_bridge
    python -m analytics.credit_equity_bridge --top 10
    python -m analytics.credit_equity_bridge --name Nokia
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from analytics.signal_scorer import (
    compute_credit_signal_score,
    compute_equity_repricing_score,
    compute_gap_score,
    CreditSignalResult,
    EquityRepricingResult,
    GapResult,
)

try:
    from analytics.trade_structurer import recommend_trade, TradeRecommendation
except ImportError:
    recommend_trade = None
    TradeRecommendation = None


# ---------------------------------------------------------------------------
# yfinance (optional)
# ---------------------------------------------------------------------------

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Cache for equity data (avoid hammering yfinance)
# ---------------------------------------------------------------------------

_equity_cache: dict[str, dict] = {}
_cache_timestamp: float = 0.0
CACHE_TTL_SECONDS = 900  # 15 min


def _is_cache_valid() -> bool:
    return (time.time() - _cache_timestamp) < CACHE_TTL_SECONDS


def _clear_cache():
    global _equity_cache, _cache_timestamp
    _equity_cache.clear()
    _cache_timestamp = 0.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EquityBridgeResult:
    """Full bridge result for a single name."""
    entity_name: str
    credit_entity: str
    equity_ticker: str | None
    sector: str
    is_public: bool
    options_available: bool

    # Credit side
    cds_spread: float
    fair_spread: float
    implied_pd_5y: float
    direction: str
    conviction: int
    rv_signal: str
    credit_signal_score: float
    credit_components: dict

    # Equity side
    stock_price: float | None
    stock_chg_5d: float | None
    stock_chg_20d: float | None
    atm_iv: float | None
    iv_percentile: float | None
    put_call_ratio: float | None
    equity_repricing_score: float | None
    equity_components: dict | None

    # Gap
    gap_score: float | None
    gap_signal: str

    # Trade recommendation
    recommended_structure: str | None
    recommended_details: dict | None

    def to_dict(self) -> dict:
        """Serialise to dict for JSON API."""
        return {
            "entity_name": self.entity_name,
            "credit_entity": self.credit_entity,
            "equity_ticker": self.equity_ticker,
            "sector": self.sector,
            "is_public": self.is_public,
            "options_available": self.options_available,
            "cds_spread": self.cds_spread,
            "fair_spread": self.fair_spread,
            "implied_pd_5y": round(self.implied_pd_5y * 100, 2) if self.implied_pd_5y else None,
            "direction": self.direction,
            "conviction": self.conviction,
            "rv_signal": self.rv_signal,
            "credit_signal_score": self.credit_signal_score,
            "credit_components": self.credit_components,
            "stock_price": self.stock_price,
            "stock_chg_5d": round(self.stock_chg_5d, 2) if self.stock_chg_5d is not None else None,
            "stock_chg_20d": round(self.stock_chg_20d, 2) if self.stock_chg_20d is not None else None,
            "atm_iv": self.atm_iv,
            "iv_percentile": self.iv_percentile,
            "put_call_ratio": self.put_call_ratio,
            "equity_repricing_score": self.equity_repricing_score,
            "equity_components": self.equity_components,
            "gap_score": self.gap_score,
            "gap_signal": self.gap_signal,
            "recommended_structure": self.recommended_structure,
            "recommended_details": self.recommended_details,
        }


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_equity_map() -> dict:
    """Load the enhanced iTraxx equity mapping."""
    path = PROJECT_ROOT / "data" / "itraxx_equity_map.json"
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return data.get("names", {})


def _load_xover_screen() -> list[dict]:
    """Load the xover screen data (spreads, direction, conviction)."""
    try:
        from data.market_data_loader import load_market_data
        md = load_market_data(index="xover")
        return md
    except Exception:
        pass

    # Fallback: try reading Excel directly
    from openpyxl import load_workbook
    outputs = Path("outputs")
    candidates = sorted(outputs.glob("xover_screen_*.xlsx"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return {}
    wb = load_workbook(str(candidates[0]), read_only=True, data_only=True)
    ws = wb.active
    result = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        name = str(row[0]).strip()
        spread = float(row[4]) if row[4] else 0.0
        if spread <= 0:
            continue
        result[name] = {
            "spread": spread,
            "fair_spread": float(row[5]) if row[5] else spread,
            "direction": str(row[1] or ""),
            "conviction": int(row[2]) if row[2] else 3,
        }
    wb.close()
    return result


def _load_rv_scores() -> dict[str, float]:
    """Load relative value composite scores."""
    try:
        from analytics.relative_value import run_full_analysis
        names, _ = run_full_analysis()
        return {n.entity_name: n.composite_score for n in names}
    except Exception:
        return {}


def _load_filings(entity_name: str) -> list[dict]:
    """Load recent filings for an entity from SQLite."""
    db_path = PROJECT_ROOT / "data" / "filings.db"
    if not db_path.exists():
        return []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """
            SELECT credit_impact, severity, headline, date
            FROM filings
            WHERE (company_name LIKE ? OR matched_entity LIKE ?)
              AND date >= ?
            ORDER BY date DESC
            LIMIT 5
            """,
            (f"%{entity_name}%", f"%{entity_name}%", cutoff),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _fetch_equity_data(ticker: str) -> dict:
    """Fetch equity price and options data from yfinance.

    Returns dict with: stock_price, chg_5d, chg_20d, atm_iv, iv_percentile, put_call_ratio
    """
    global _equity_cache, _cache_timestamp

    if ticker in _equity_cache and _is_cache_valid():
        return _equity_cache[ticker]

    result = {
        "stock_price": None,
        "chg_5d": None,
        "chg_20d": None,
        "atm_iv": None,
        "iv_percentile": None,
        "put_call_ratio": None,
    }

    if not YFINANCE_AVAILABLE or not ticker:
        _equity_cache[ticker] = result
        return result

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="3mo")

        if hist is None or hist.empty:
            _equity_cache[ticker] = result
            return result

        # Current price
        current = hist["Close"].iloc[-1]
        result["stock_price"] = round(float(current), 2)

        # 5-day change
        if len(hist) >= 6:
            price_5d = hist["Close"].iloc[-6]
            result["chg_5d"] = round((current - price_5d) / price_5d * 100, 2)

        # 20-day change
        if len(hist) >= 21:
            price_20d = hist["Close"].iloc[-21]
            result["chg_20d"] = round((current - price_20d) / price_20d * 100, 2)

        # Options data
        try:
            expirations = stock.options
            if expirations:
                # Find 30-60 day expiry
                today = datetime.now().date()
                target_exp = expirations[0]
                for exp in expirations:
                    exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                    days = (exp_date - today).days
                    if 20 <= days <= 60:
                        target_exp = exp
                        break

                chain = stock.option_chain(target_exp)
                calls = chain.calls
                puts = chain.puts

                # ATM strike
                if not calls.empty:
                    atm_idx = (calls["strike"] - current).abs().idxmin()
                    atm_strike = calls.loc[atm_idx, "strike"]

                    # ATM IV
                    call_iv = calls.loc[calls["strike"] == atm_strike, "impliedVolatility"]
                    put_iv = puts.loc[puts["strike"] == atm_strike, "impliedVolatility"]

                    ivs = []
                    if not call_iv.empty:
                        ivs.append(float(call_iv.iloc[0]))
                    if not put_iv.empty:
                        ivs.append(float(put_iv.iloc[0]))
                    if ivs:
                        result["atm_iv"] = round(mean(ivs) * 100, 1)

                    # Put/call volume ratio
                    total_call_vol = calls["volume"].sum()
                    total_put_vol = puts["volume"].sum()
                    if total_call_vol and total_call_vol > 0:
                        result["put_call_ratio"] = round(
                            float(total_put_vol / total_call_vol), 2
                        )

                # IV percentile (use realized vol as proxy)
                if len(hist) >= 60:
                    returns = hist["Close"].pct_change().dropna()
                    hv_20 = float(returns[-20:].std()) * (252 ** 0.5) * 100
                    hv_60 = float(returns[-60:].std()) * (252 ** 0.5) * 100

                    if result["atm_iv"] is not None and hv_60 > 0:
                        # Rough IV percentile: current IV vs HV range
                        ratio = result["atm_iv"] / hv_60
                        result["iv_percentile"] = round(
                            min(100, max(0, (ratio - 0.5) / 1.5 * 100)), 1
                        )

        except Exception:
            pass  # Options data not available for all tickers

    except Exception:
        pass

    _equity_cache[ticker] = result
    _cache_timestamp = time.time()
    return result


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def _fuzzy_match_name(screen_name: str, equity_map: dict) -> str | None:
    """Try to match a screen name to an equity map entry."""
    # Exact match
    if screen_name in equity_map:
        return screen_name

    # Try screen_name field
    for map_key, info in equity_map.items():
        if info.get("screen_name", "").lower() == screen_name.lower():
            return map_key

    # Fuzzy: match on significant words
    screen_words = set(
        w.lower()
        for w in screen_name.replace(".", " ").replace(",", " ").split()
        if len(w) > 2 and w.lower() not in {
            "plc", "ltd", "sarl", "bv", "sa", "ag", "se", "ab",
            "spa", "sas", "gmbh", "oyj", "the", "and", "for",
            "finance", "holding", "group", "international",
        }
    )

    best_match = None
    best_overlap = 0

    for map_key, info in equity_map.items():
        map_words = set(
            w.lower()
            for w in map_key.replace(".", " ").replace(",", " ").split()
            if len(w) > 2 and w.lower() not in {
                "plc", "ltd", "sarl", "bv", "sa", "ag", "se", "ab",
                "spa", "sas", "gmbh", "oyj", "the", "and", "for",
                "finance", "holding", "group", "international",
            }
        )
        overlap = len(screen_words & map_words)
        if overlap > best_overlap and overlap >= 1:
            best_match = map_key
            best_overlap = overlap

    return best_match


# ---------------------------------------------------------------------------
# Sector stats helper
# ---------------------------------------------------------------------------

def _compute_sector_stats(
    screen_data: dict, equity_map: dict
) -> dict[str, dict]:
    """Compute average spread per sector."""
    sector_spreads: dict[str, list[float]] = {}

    for name, data in screen_data.items():
        spread = data.get("spread") if isinstance(data, dict) else None
        if not spread or spread <= 0:
            continue

        # Find sector
        map_key = _fuzzy_match_name(name, equity_map)
        if map_key:
            sector = equity_map[map_key].get("sector", "Other")
        else:
            sector = "Other"

        sector_spreads.setdefault(sector, []).append(spread)

    result = {}
    for sector, spreads in sector_spreads.items():
        result[sector] = {
            "avg_spread": mean(spreads) if spreads else 0,
            "count": len(spreads),
        }
    return result


# ---------------------------------------------------------------------------
# Main bridge function
# ---------------------------------------------------------------------------

def run_equity_bridge(
    top_n: int = 0,
    name_filter: str | None = None,
    fetch_equity: bool = True,
) -> list[EquityBridgeResult]:
    """Run the full credit-equity bridge analysis.

    Args:
        top_n: Return only top N by gap score (0 = all public names)
        name_filter: Filter to a specific name (partial match)
        fetch_equity: Whether to fetch live equity data (slow)

    Returns:
        List of EquityBridgeResult sorted by gap_score descending
    """
    from analytics.cds_pricer import implied_default_probability

    # Load all data sources
    equity_map = _load_equity_map()
    screen_data = _load_xover_screen()
    rv_scores = _load_rv_scores()
    sector_stats = _compute_sector_stats(screen_data, equity_map)

    results: list[EquityBridgeResult] = []

    # Build unified name list: prefer screen data, fall back to equity map
    # This ensures the bridge works even when no Excel screen data is present
    name_entries: list[tuple[str, str, dict, dict]] = []
    # (screen_name, map_key, spread_data, map_info)

    if screen_data and isinstance(screen_data, dict):
        for screen_name, sdata in screen_data.items():
            if not isinstance(sdata, dict):
                continue
            spread = sdata.get("spread", 0)
            if not spread or spread <= 0:
                continue
            map_key = _fuzzy_match_name(screen_name, equity_map)
            if not map_key:
                continue
            name_entries.append((screen_name, map_key, sdata, equity_map[map_key]))
    else:
        # Fallback: use equity map directly with index average spread
        avg_xover_spread = 250.0  # iTraxx Xover S44 average as default
        for map_key, info in equity_map.items():
            if not info.get("is_public", False):
                continue
            screen_name = info.get("screen_name", map_key)
            # Use sector heuristic for spread
            sector = info.get("sector", "Other")
            sector_spread_map = {
                "Consumers": 280, "Autos & Industrials": 310,
                "TMT": 240, "Energy": 350, "Financials": 200,
            }
            spread = sector_spread_map.get(sector, avg_xover_spread)
            sdata = {
                "spread": spread,
                "fair_spread": spread,
                "direction": "",
                "conviction": 3,
            }
            name_entries.append((screen_name, map_key, sdata, info))

    for screen_name, map_key, sdata, info in name_entries:
        spread = sdata.get("spread", 0)
        fair_spread = sdata.get("fair_spread", spread)
        direction = sdata.get("direction", "")
        conviction = sdata.get("conviction", 3)

        ticker = info.get("equity_ticker")
        is_public = info.get("is_public", False)
        options_available = info.get("options_available", False)
        sector = info.get("sector", "Other")
        credit_entity = info.get("credit_entity", map_key)

        # Skip private companies (no equity data)
        if not is_public:
            continue

        # Name filter
        if name_filter:
            if (
                name_filter.lower() not in screen_name.lower()
                and name_filter.lower() not in map_key.lower()
                and name_filter.lower() not in (ticker or "").lower()
            ):
                continue

        # Get filings
        filings = _load_filings(screen_name)

        # Get RV score
        rv = rv_scores.get(screen_name)

        # Get sector data
        sec = sector_stats.get(sector, {})
        sector_avg = sec.get("avg_spread")

        # Compute credit signal score
        credit_result = compute_credit_signal_score(
            entity_name=screen_name,
            spread_bps=spread,
            fair_spread=fair_spread,
            direction=direction,
            conviction=conviction,
            filings=filings,
            maturity_risk=None,  # Would need maturity data
            rv_composite=rv,
            sector_avg_spread=sector_avg,
        )

        # Compute implied PD
        pd_5y = implied_default_probability(spread)

        # Get equity data
        equity_data = {}
        equity_result = None
        gap_result = None

        if fetch_equity and ticker:
            equity_data = _fetch_equity_data(ticker)

            if equity_data.get("stock_price") is not None:
                equity_result = compute_equity_repricing_score(
                    ticker=ticker,
                    stock_price_5d_chg=equity_data.get("chg_5d"),
                    stock_price_20d_chg=equity_data.get("chg_20d"),
                    iv_percentile=equity_data.get("iv_percentile"),
                    put_call_ratio=equity_data.get("put_call_ratio"),
                )

                gap_result = compute_gap_score(
                    entity_name=screen_name,
                    ticker=ticker,
                    credit_result=credit_result,
                    equity_result=equity_result,
                )

        # Trade recommendation
        rec_structure = None
        rec_details = None
        if recommend_trade and gap_result and gap_result.gap_signal in ("STRONG", "MODERATE"):
            try:
                rec = recommend_trade(
                    catalyst_type="maturity_wall",  # Default; would be refined
                    iv_percentile=equity_data.get("iv_percentile"),
                    gap_signal=gap_result.gap_signal,
                    spread_bps=spread,
                )
                rec_structure = rec.structure
                rec_details = asdict(rec)
            except Exception:
                pass

        results.append(EquityBridgeResult(
            entity_name=screen_name,
            credit_entity=credit_entity,
            equity_ticker=ticker,
            sector=sector,
            is_public=is_public,
            options_available=options_available,
            cds_spread=spread,
            fair_spread=fair_spread,
            implied_pd_5y=pd_5y,
            direction=direction,
            conviction=conviction,
            rv_signal="CHEAP" if (rv and rv > 0.5) else "RICH" if (rv and rv < -0.5) else "FAIR",
            credit_signal_score=credit_result.total_score,
            credit_components=credit_result.components,
            stock_price=equity_data.get("stock_price"),
            stock_chg_5d=equity_data.get("chg_5d"),
            stock_chg_20d=equity_data.get("chg_20d"),
            atm_iv=equity_data.get("atm_iv"),
            iv_percentile=equity_data.get("iv_percentile"),
            put_call_ratio=equity_data.get("put_call_ratio"),
            equity_repricing_score=equity_result.total_score if equity_result else None,
            equity_components=equity_result.components if equity_result else None,
            gap_score=gap_result.gap_score if gap_result else None,
            gap_signal=gap_result.gap_signal if gap_result else "N/A",
            recommended_structure=rec_structure,
            recommended_details=rec_details,
        ))

    # Sort by gap score (descending), credit-only names at end
    results.sort(
        key=lambda r: (
            r.gap_score if r.gap_score is not None else -999,
        ),
        reverse=True,
    )

    if top_n > 0:
        results = results[:top_n]

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Credit-Equity Options Bridge")
    parser.add_argument("--top", type=int, default=0, help="Show only top N")
    parser.add_argument("--name", type=str, default=None, help="Filter by name")
    parser.add_argument(
        "--no-equity", action="store_true",
        help="Skip equity data fetch (credit scores only)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 90)
    print("  CREDIT-EQUITY OPTIONS BRIDGE -- The Alpha Engine")
    print("=" * 90)

    fetch = not args.no_equity
    if not YFINANCE_AVAILABLE:
        print("  [WARN] yfinance not installed -- credit scores only")
        fetch = False

    results = run_equity_bridge(
        top_n=args.top,
        name_filter=args.name,
        fetch_equity=fetch,
    )

    if not results:
        print("\n  No results found.\n")
        return

    # Print header
    print(f"\n  {'Entity':<30} {'Ticker':<10} {'Sector':<18} "
          f"{'Spread':>7} {'Credit':>7} {'Equity':>7} {'Gap':>6} {'Signal':<10} {'Structure':<15}")
    print("  " + "-" * 128)

    for r in results:
        eq_str = f"{r.equity_repricing_score:.0f}" if r.equity_repricing_score is not None else "N/A"
        gap_str = f"{r.gap_score:+.0f}" if r.gap_score is not None else "N/A"
        struct = r.recommended_structure or "-"

        print(f"  {r.entity_name[:30]:<30} {(r.equity_ticker or '-'):<10} {r.sector[:18]:<18} "
              f"{r.cds_spread:>7.0f} {r.credit_signal_score:>7.0f} "
              f"{eq_str:>7} {gap_str:>6} {r.gap_signal:<10} {struct:<15}")

    print(f"\n  Total: {len(results)} public names scored")
    if not fetch:
        print("  [NOTE] Equity data not fetched -- gap scores unavailable")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
