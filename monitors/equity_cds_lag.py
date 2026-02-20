"""
Equity-CDS Lag Monitor

Monitors for equity price drops in Xover S44 universe names and alerts
when CDS hasn't repriced yet. The thesis: when a company's equity drops
3%+ intraday on news, the CDS market often takes 30-60 minutes to reprice,
especially in European hours. This lag is a tradeable signal.

Usage:
    python -m monitors.equity_cds_lag
    python -m monitors.equity_cds_lag --threshold 5.0   # 5% drop threshold
    python -m monitors.equity_cds_lag --json             # JSON output
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import yfinance as yf

from data.market_data_loader import load_market_data


# ---------------------------------------------------------------------------
# Xover S44 -> Equity ticker mapping
# Only names with publicly listed equity. Private / sponsor-owned names
# (INEOS, Merlin, Aggreko, Iceland, Stena, ZF, etc.) are excluded.
# ---------------------------------------------------------------------------
EQUITY_MAP = {
    # Consumers
    "Air France-KLM":                          {"ticker": "AF.PA",   "exchange": "Euronext Paris"},
    "CECONOMY AG":                             {"ticker": "CEC.DE",  "exchange": "Xetra"},
    "Grifols SA":                              {"ticker": "GRF.MC",  "exchange": "Madrid"},
    "Lagardere SA":                            {"ticker": "MMB.PA",  "exchange": "Euronext Paris"},
    "Lottomatica Group Spa":                   {"ticker": "LTMC.MI", "exchange": "Milan"},
    "Premier Foods Finance PLC":               {"ticker": "PFD.L",   "exchange": "LSE"},
    "TUI AG":                                  {"ticker": "TUI1.DE", "exchange": "Xetra"},
    "Verisure Midholding AB":                  {"ticker": "VSURE.ST","exchange": "Stockholm (Verisure plc)"},

    # Autos & Industrials
    # CMA CGM SA: private (Saade family 73%), no public equity listing

    "Constellium SE":                          {"ticker": "CSTM",    "exchange": "NYSE"},
    "Forvia SE":                               {"ticker": "FRVIA.PA","exchange": "Euronext Paris"},
    "Hapag-Lloyd AG":                          {"ticker": "HLAG.DE", "exchange": "Xetra"},
    "Jaguar Land Rover Automotive PLC":        {"ticker": "TTML.NS", "exchange": "NSE (Tata Motors)"},
    "LANXESS AG":                              {"ticker": "LXS.DE",  "exchange": "Xetra"},
    "Metsa Board Oyj":                         {"ticker": "METSB.HE","exchange": "Helsinki"},
    # Mundys SpA: delisted Dec 2022 (Benetton/Blackstone buyout), now private

    "OI European Group BV":                    {"ticker": "OI",      "exchange": "NYSE"},
    "Renault SA":                              {"ticker": "RNO.PA",  "exchange": "Euronext Paris"},
    "Rexel SA":                                {"ticker": "RXL.PA",  "exchange": "Euronext Paris"},
    "Schaeffler AG":                           {"ticker": "SHA0.DE", "exchange": "Xetra"},
    # Stena AB: private (Olsson family), no public equity listing

    # Syngenta AG: delisted 2017 (ChemChina acquisition), Shanghai IPO withdrawn 2024

    "Valeo SE":                                {"ticker": "FR.PA",   "exchange": "Euronext Paris"},
    "Volvo Car AB":                            {"ticker": "VOLCAR-B.ST","exchange": "Stockholm"},
    "Webuild SpA":                             {"ticker": "WBD.MI",  "exchange": "Milan"},
    # ZF Europe Finance BV: private (Zeppelin Foundation), no public equity listing


    # TMT
    "Eutelsat SA":                             {"ticker": "ETL.PA",  "exchange": "Euronext Paris"},
    "Nexi SpA":                                {"ticker": "NEXI.MI", "exchange": "Milan"},
    "Nokia Oyj":                               {"ticker": "NOKIA.HE","exchange": "Helsinki"},
    "SES SA":                                  {"ticker": "SESG.PA", "exchange": "Euronext Paris"},
    "Telecom Italia SpA/Milano":               {"ticker": "TIT.MI",  "exchange": "Milan"},
    "Telefonaktiebolaget LM Ericsson":         {"ticker": "ERIC-B.ST","exchange": "Stockholm"},
    # United Group BV: private (BC Partners), no public equity listing

    "Worldline SA/France":                     {"ticker": "WLN.PA",  "exchange": "Euronext Paris"},

    # Financials
    "CPI Property Group SA":                   {"ticker": "O5G.DE",  "exchange": "Xetra (Frankfurt)"},
    "Samhallsbyggnadsbolaget i Norden AB":     {"ticker": "SBB-B.ST","exchange": "Stockholm"},

    # Energy
    "Public Power Corp SA":                    {"ticker": "PPC.AT",  "exchange": "Athens"},
    "Saipem Finance International BV":         {"ticker": "SPM.MI",  "exchange": "Milan"},
}


# Approximate CDS beta to equity: how many bps CDS should widen per 1% equity drop
# Higher for HY names, lower for IG-crossover
CDS_EQUITY_BETA = {
    "default": 8.0,       # 8bps per 1% equity drop (typical BB)
    "high_spread": 15.0,  # >400bps names: more leveraged, higher beta
    "low_spread": 4.0,    # <100bps names: IG-like, lower beta
    "distressed": 25.0,   # >800bps names: equity vol maps heavily to CDS
}


def get_cds_beta(current_spread: float | None) -> float:
    """Estimate CDS-equity beta based on current spread level."""
    if current_spread is None:
        return CDS_EQUITY_BETA["default"]
    if current_spread > 800:
        return CDS_EQUITY_BETA["distressed"]
    if current_spread > 400:
        return CDS_EQUITY_BETA["high_spread"]
    if current_spread < 100:
        return CDS_EQUITY_BETA["low_spread"]
    return CDS_EQUITY_BETA["default"]


def fetch_intraday_moves(tickers: dict[str, dict], period: str = "1d") -> dict:
    """Fetch intraday equity moves for all mapped tickers.

    Returns dict of {xover_name: {ticker, open, current, change_pct, volume, ...}}
    """
    results = {}
    ticker_symbols = []
    name_by_ticker = {}

    for xover_name, info in tickers.items():
        sym = info["ticker"]
        ticker_symbols.append(sym)
        name_by_ticker[sym] = xover_name

    if not ticker_symbols:
        return results

    # Batch download for efficiency
    print(f"  Fetching equity data for {len(ticker_symbols)} tickers...", flush=True)

    for xover_name, info in tickers.items():
        sym = info["ticker"]
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period=period, interval="1d")

            if hist.empty:
                continue

            latest = hist.iloc[-1]
            open_price = float(latest["Open"])
            close_price = float(latest["Close"])
            high = float(latest["High"])
            low = float(latest["Low"])
            volume = int(latest["Volume"])

            if open_price <= 0:
                continue

            change_pct = ((close_price - open_price) / open_price) * 100
            intraday_range = ((high - low) / open_price) * 100

            results[xover_name] = {
                "ticker": sym,
                "exchange": info["exchange"],
                "open": round(open_price, 4),
                "close": round(close_price, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "change_pct": round(change_pct, 2),
                "intraday_range_pct": round(intraday_range, 2),
                "volume": volume,
                "date": str(hist.index[-1].date()),
            }
        except Exception as e:
            # Skip failed tickers silently
            pass

    return results


def scan_for_lag_opportunities(
    equity_moves: dict,
    market_data: dict,
    threshold: float = -3.0,
) -> list[dict]:
    """Cross-reference equity drops with CDS spreads to find lag opportunities.

    Args:
        equity_moves: Dict from fetch_intraday_moves
        market_data: Dict from load_market_data
        threshold: Equity drop threshold (negative, e.g. -3.0 for 3% drop)

    Returns:
        List of lag opportunity dicts, sorted by opportunity score desc.
    """
    opportunities = []

    for xover_name, eq in equity_moves.items():
        change = eq["change_pct"]

        # Skip if equity didn't drop enough
        if change > threshold:
            continue

        # Get CDS data
        cds = market_data.get(xover_name, {})
        current_spread = cds.get("spread")

        if current_spread is None:
            continue

        # Calculate expected CDS widening
        beta = get_cds_beta(current_spread)
        equity_drop = abs(change)
        expected_cds_move = equity_drop * beta  # bps widening expected

        # Score: higher = bigger opportunity
        # Based on equity drop magnitude and expected CDS move relative to spread
        expected_move_pct = (expected_cds_move / current_spread) * 100
        opportunity_score = equity_drop * expected_move_pct

        opportunities.append({
            "entity": xover_name,
            "ticker": eq["ticker"],
            "exchange": eq["exchange"],
            "equity_change_pct": change,
            "equity_open": eq["open"],
            "equity_close": eq["close"],
            "equity_volume": eq["volume"],
            "date": eq["date"],
            "cds_spread": current_spread,
            "cds_convention": cds.get("convention", "Spread"),
            "cds_points_upfront": cds.get("points_upfront"),
            "expected_cds_move_bps": round(expected_cds_move, 1),
            "expected_new_spread": round(current_spread + expected_cds_move, 1),
            "cds_equity_beta": beta,
            "opportunity_score": round(opportunity_score, 2),
        })

    # Sort by opportunity score descending
    opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return opportunities


def print_scan_report(
    equity_moves: dict,
    opportunities: list[dict],
    market_data: dict,
    threshold: float,
):
    """Print formatted scan report."""
    today = datetime.now().strftime("%d %B %Y %H:%M")

    print("=" * 110)
    print("  STRATEGIES IN CREDIT -- EQUITY-CDS LAG MONITOR")
    print(f"  {today}")
    print("=" * 110)

    print(f"\n  Equity tickers mapped:  {len(EQUITY_MAP)}")
    print(f"  Equity data retrieved:  {len(equity_moves)}")
    print(f"  Drop threshold:         {threshold:.1f}%")
    print(f"  Lag opportunities:      {len(opportunities)}")

    # Show all equity moves sorted by change
    print("\n" + "-" * 110)
    print("  ALL EQUITY MOVES (sorted by change)")
    print("-" * 110)
    print(f"  {'Entity':<42} {'Ticker':<12} {'Change':>7} {'Open':>10} {'Close':>10} {'Volume':>12}")
    print("  " + "-" * 105)

    sorted_moves = sorted(equity_moves.items(), key=lambda x: x[1]["change_pct"])
    for name, eq in sorted_moves:
        flag = " <--" if eq["change_pct"] <= threshold else ""
        print(f"  {name[:40]:<42} {eq['ticker']:<12} {eq['change_pct']:>+6.2f}% "
              f"{eq['open']:>10.2f} {eq['close']:>10.2f} {eq['volume']:>12,}{flag}")

    # Lag opportunities detail
    if opportunities:
        print("\n" + "=" * 110)
        print("  LAG OPPORTUNITIES -- CDS NOT YET REPRICED")
        print("=" * 110)

        for i, opp in enumerate(opportunities, 1):
            print(f"\n  #{i}  {opp['entity']}")
            print(f"      Equity: {opp['ticker']} ({opp['exchange']})")
            print(f"      Move:   {opp['equity_change_pct']:+.2f}% "
                  f"({opp['equity_open']:.2f} -> {opp['equity_close']:.2f})")
            print(f"      CDS:    {opp['cds_spread']:.0f}bps current "
                  f"({opp['cds_convention']})")
            if opp['cds_points_upfront']:
                print(f"              Points upfront: {opp['cds_points_upfront']:.2f}")
            print(f"      Expected CDS widening: +{opp['expected_cds_move_bps']:.0f}bps "
                  f"-> {opp['expected_new_spread']:.0f}bps")
            print(f"      Beta:   {opp['cds_equity_beta']:.0f}bps per 1% equity drop")
            print(f"      Score:  {opp['opportunity_score']:.1f}")
            print(f"      ACTION: Buy CDS protection at {opp['cds_spread']:.0f}bps, "
                  f"target {opp['expected_new_spread']:.0f}bps")
    else:
        print("\n  No lag opportunities detected today.")
        print("  (No equity dropped more than {:.1f}% intraday)".format(abs(threshold)))

    print("\n" + "-" * 110)
    print("  Thesis: Equity reprices faster than CDS on news events.")
    print("  Edge window: 30-60 mins in European hours (8am-4pm CET).")
    print("  Source: Yahoo Finance (equity) | Bloomberg (CDS)")
    print("-" * 110)


def main():
    parser = argparse.ArgumentParser(description="Equity-CDS Lag Monitor")
    parser.add_argument(
        "--threshold", type=float, default=-3.0,
        help="Equity drop threshold in %% (default: -3.0)",
    )
    parser.add_argument(
        "--period", type=str, default="1d",
        choices=["1d", "5d"],
        help="Lookback period (default: 1d)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of formatted report",
    )
    args = parser.parse_args()

    # Load CDS market data
    market_data = load_market_data(index="xover")
    if not market_data:
        print("Error: No CDS market data found.", file=sys.stderr)
        sys.exit(1)

    # Fetch equity moves
    equity_moves = fetch_intraday_moves(EQUITY_MAP, period=args.period)

    if not equity_moves:
        print("Warning: No equity data retrieved. Markets may be closed.",
              file=sys.stderr)

    # Scan for lag opportunities
    opportunities = scan_for_lag_opportunities(
        equity_moves, market_data, threshold=args.threshold
    )

    if args.json:
        output = {
            "generated_at": datetime.now().isoformat(),
            "threshold_pct": args.threshold,
            "tickers_mapped": len(EQUITY_MAP),
            "equity_data_retrieved": len(equity_moves),
            "opportunities": opportunities,
            "all_moves": equity_moves,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print_scan_report(equity_moves, opportunities, market_data, args.threshold)


if __name__ == "__main__":
    main()
