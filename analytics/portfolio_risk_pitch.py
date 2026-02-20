"""
Portfolio Risk Metrics for Pitch Deck — Strategies in Credit

Computes real risk metrics for the 10-position portfolio at $500M NAV
using the ISDA Standard CDS pricer. Output formatted for pod shop
allocator pitch deck (slide 5).

Metrics:
    1. Net DV01 (signed — negative for net short)
    2. Gross CS01
    3. Gross JTD exposure
    4. Max single-name JTD as % of NAV
    5. Net carry p.a.
    6. Stress P&L: -50bp, +100bp, +200bp, all shorts default, all longs default

Usage:
    python -m analytics.portfolio_risk_pitch
    python -m analytics.portfolio_risk_pitch --csv outputs/custom.csv
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

from analytics.cds_pricer import (
    cds_dv01,
    cds_cs01,
    jump_to_default,
    price_cds,
    implied_default_probability,
    _risky_annuity,
    ISDA_RECOVERY,
)

# ---------------------------------------------------------------------------
# Portfolio definition — Slide 5 positions
# ---------------------------------------------------------------------------

NAV = 500_000_000  # $500M

# direction: "SHORT" = sell protection (short risk), "LONG" = buy protection (long risk)
POSITIONS = [
    {"name": "CECONOMY",           "direction": "SHORT", "size_pct": 5.0,  "spread_bps": 64},
    {"name": "Kaixo Bondco",       "direction": "SHORT", "size_pct": 5.0,  "spread_bps": 50},
    {"name": "INEOS Quattro",      "direction": "LONG",  "size_pct": 2.0,  "spread_bps": 1224},
    {"name": "Worldline",          "direction": "LONG",  "size_pct": 2.0,  "spread_bps": 1027},
    {"name": "Sunrise HoldCo",     "direction": "SHORT", "size_pct": 4.5,  "spread_bps": 75},
    {"name": "Syngenta",           "direction": "SHORT", "size_pct": 4.0,  "spread_bps": 90},
    {"name": "Cirsa Finance",      "direction": "SHORT", "size_pct": 3.5,  "spread_bps": 200},
    {"name": "INEOS Finance",      "direction": "LONG",  "size_pct": 1.5,  "spread_bps": 908},
    {"name": "Eutelsat",           "direction": "SHORT", "size_pct": 3.0,  "spread_bps": 106},
    {"name": "Sherwood Financing", "direction": "LONG",  "size_pct": 1.5,  "spread_bps": 585},
]

# Spread bump scenarios (bps)
SPREAD_BUMPS = [-50, +100, +200]


# ---------------------------------------------------------------------------
# Per-name risk computation
# ---------------------------------------------------------------------------

def compute_name_risks(positions: list[dict], nav: float) -> list[dict]:
    """Compute risk metrics for each position."""
    results = []

    for pos in positions:
        name = pos["name"]
        direction = pos["direction"]
        spread = pos["spread_bps"]
        notional = nav * pos["size_pct"] / 100.0
        is_long = direction == "LONG"  # long risk = buy protection

        # Unsigned DV01 / CS01
        dv01 = cds_dv01(spread, notional=notional)
        cs01 = cds_cs01(spread, notional=notional)

        # Signed DV01:
        # LONG risk (buy protection): +DV01 (profit when spreads widen)
        # SHORT risk (sell protection): -DV01 (loss when spreads widen)
        signed_dv01 = dv01 if is_long else -dv01

        # JTD (already signed by the pricer)
        jtd = jump_to_default(
            spread, notional=notional,
            is_protection_buyer=is_long,
        )

        # RPV01 and carry
        rpv01 = _risky_annuity(spread)
        # Annual carry = spread × notional / 10,000
        # Sell protection (SHORT) → receive carry (positive)
        # Buy protection (LONG) → pay carry (negative)
        annual_carry = spread / 10_000 * notional
        signed_carry = annual_carry if not is_long else -annual_carry

        # 5Y default probability
        pd_5y = implied_default_probability(spread)

        # Stress P&L per name (full repricing via price_cds)
        stress_pnl = {}
        for bump in SPREAD_BUMPS:
            bumped_spread = max(1.0, spread + bump)
            # price_cds: MTM of a CDS position entered at trade_spread,
            # now marked at market_spread.
            # For protection buyer (is_long): profit when spreads widen
            # For protection seller (not is_long): profit when spreads tighten
            pnl = price_cds(
                trade_spread_bps=spread,
                market_spread_bps=bumped_spread,
                notional=notional,
                is_protection_buyer=is_long,
            )
            stress_pnl[bump] = pnl

        results.append({
            "name": name,
            "direction": direction,
            "size_pct": pos["size_pct"],
            "notional": notional,
            "spread_bps": spread,
            "dv01": dv01,
            "signed_dv01": signed_dv01,
            "cs01": cs01,
            "jtd": jtd,
            "rpv01": rpv01,
            "signed_carry": signed_carry,
            "pd_5y": pd_5y,
            "stress_pnl": stress_pnl,
        })

    return results


# ---------------------------------------------------------------------------
# Portfolio aggregation
# ---------------------------------------------------------------------------

def aggregate_portfolio(name_risks: list[dict], nav: float) -> dict:
    """Aggregate per-name risks into portfolio-level metrics."""

    net_dv01 = sum(r["signed_dv01"] for r in name_risks)
    gross_cs01 = sum(abs(r["cs01"]) for r in name_risks)
    gross_jtd = sum(abs(r["jtd"]) for r in name_risks)
    net_carry = sum(r["signed_carry"] for r in name_risks)

    # Max single-name JTD
    max_jtd_name = max(name_risks, key=lambda r: abs(r["jtd"]))
    max_jtd = abs(max_jtd_name["jtd"])
    max_jtd_pct_nav = max_jtd / nav * 100

    # Exposure totals
    long_notional = sum(r["notional"] for r in name_risks if r["direction"] == "LONG")
    short_notional = sum(r["notional"] for r in name_risks if r["direction"] == "SHORT")
    gross_notional = long_notional + short_notional
    net_notional = short_notional - long_notional  # net short → positive

    # Stress scenarios: spread bumps
    stress_totals = {}
    for bump in SPREAD_BUMPS:
        stress_totals[bump] = sum(r["stress_pnl"][bump] for r in name_risks)

    # Default scenarios
    # All shorts default: protection sellers pay LGD
    shorts_default_pnl = sum(
        r["jtd"] for r in name_risks if r["direction"] == "SHORT"
    )
    # All longs default: protection buyers receive LGD
    longs_default_pnl = sum(
        r["jtd"] for r in name_risks if r["direction"] == "LONG"
    )

    return {
        "net_dv01": net_dv01,
        "gross_cs01": gross_cs01,
        "gross_jtd": gross_jtd,
        "max_jtd": max_jtd,
        "max_jtd_name": max_jtd_name["name"],
        "max_jtd_pct_nav": max_jtd_pct_nav,
        "net_carry": net_carry,
        "net_carry_bps_nav": net_carry / nav * 10_000,
        "long_notional": long_notional,
        "short_notional": short_notional,
        "gross_notional": gross_notional,
        "net_notional": net_notional,
        "stress_totals": stress_totals,
        "shorts_default_pnl": shorts_default_pnl,
        "longs_default_pnl": longs_default_pnl,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_report(name_risks: list[dict], portfolio: dict, nav: float):
    """Print formatted risk dashboard for pitch deck."""
    W = 120
    today = datetime.now().strftime("%Y-%m-%d")

    print()
    print("=" * W)
    print("  STRATEGIES IN CREDIT — Portfolio Risk Metrics")
    print(f"  {today}  |  NAV: ${nav/1e6:.0f}M  |  Recovery: {ISDA_RECOVERY:.0%}  |  Maturity: 5Y")
    print("=" * W)

    # --- Exposure Summary ---
    print()
    print("  EXPOSURE SUMMARY")
    print("  " + "-" * (W - 4))
    print(f"    Long notional:   ${portfolio['long_notional']/1e6:>8.1f}M  "
          f"({portfolio['long_notional']/nav*100:>5.1f}% of NAV)")
    print(f"    Short notional:  ${portfolio['short_notional']/1e6:>8.1f}M  "
          f"({portfolio['short_notional']/nav*100:>5.1f}% of NAV)")
    print(f"    Gross notional:  ${portfolio['gross_notional']/1e6:>8.1f}M  "
          f"({portfolio['gross_notional']/nav*100:>5.1f}% of NAV)")
    print(f"    Net notional:    ${portfolio['net_notional']/1e6:>+8.1f}M  "
          f"({portfolio['net_notional']/nav*100:>+5.1f}% of NAV)  [net short]")

    # --- Key Risk Metrics ---
    print()
    print("  KEY RISK METRICS")
    print("  " + "-" * (W - 4))
    print(f"    1. Net DV01:              ${portfolio['net_dv01']:>+12,.0f}  "
          f"({portfolio['net_dv01']/nav*10000:>+.2f} bp of NAV per 1bp)")
    print(f"    2. Gross CS01:            ${portfolio['gross_cs01']:>12,.0f}  "
          f"({portfolio['gross_cs01']/nav*10000:.2f} bp of NAV per 1bp)")
    print(f"    3. Gross JTD Exposure:    ${portfolio['gross_jtd']:>12,.0f}  "
          f"({portfolio['gross_jtd']/nav*100:.1f}% of NAV)")
    print(f"    4. Max Single-Name JTD:   ${portfolio['max_jtd']:>12,.0f}  "
          f"({portfolio['max_jtd_pct_nav']:.1f}% of NAV)  "
          f"[{portfolio['max_jtd_name']}]")
    print(f"    5. Net Carry p.a.:        ${portfolio['net_carry']:>+12,.0f}  "
          f"({portfolio['net_carry_bps_nav']:>+.0f} bp of NAV)")

    # --- Per-Name Detail ---
    print()
    print("  PER-NAME RISK DETAIL")
    print("  " + "-" * (W - 4))
    print(f"  {'Name':<22} {'Dir':>5} {'Size':>5} {'Spread':>7} "
          f"{'DV01':>10} {'SignedDV01':>11} {'JTD':>12} "
          f"{'Carry p.a.':>12} {'5Y PD':>6}")
    print(f"  {'-'*22} {'-'*5} {'-'*5} {'-'*7} "
          f"{'-'*10} {'-'*11} {'-'*12} "
          f"{'-'*12} {'-'*6}")

    for r in name_risks:
        print(f"  {r['name']:<22} {r['direction']:>5} {r['size_pct']:>4.1f}% "
              f"{r['spread_bps']:>6.0f}bp "
              f"${r['dv01']:>9,.0f} ${r['signed_dv01']:>+10,.0f} "
              f"${r['jtd']:>+11,.0f} "
              f"${r['signed_carry']:>+11,.0f} "
              f"{r['pd_5y']:>5.1%}")

    # Totals row
    print(f"  {'-'*22} {'-'*5} {'-'*5} {'-'*7} "
          f"{'-'*10} {'-'*11} {'-'*12} "
          f"{'-'*12} {'-'*6}")
    total_dv01 = sum(r['dv01'] for r in name_risks)
    print(f"  {'TOTAL':<22} {'':>5} {'32.0':>4}% "
          f"{'':>7} "
          f"${total_dv01:>9,.0f} ${portfolio['net_dv01']:>+10,.0f} "
          f"{'':>12} "
          f"${portfolio['net_carry']:>+11,.0f} "
          f"{'':>6}")

    # --- Stress P&L ---
    print()
    print("  STRESS P&L SCENARIOS")
    print("  " + "-" * (W - 4))

    # Spread bump scenarios
    print()
    print(f"  {'Name':<22}", end="")
    for bump in SPREAD_BUMPS:
        print(f"  {bump:+d}bp".rjust(14), end="")
    print(f"  {'ShortsDflt':>14}  {'LongsDflt':>14}")

    print(f"  {'-'*22}", end="")
    for _ in SPREAD_BUMPS:
        print(f"  {'-'*12}", end="")
    print(f"  {'-'*14}  {'-'*14}")

    for r in name_risks:
        line = f"  {r['name']:<22}"
        for bump in SPREAD_BUMPS:
            pnl = r["stress_pnl"][bump]
            if abs(pnl) >= 1_000_000:
                line += f"  ${pnl/1e6:>+11.2f}M"
            else:
                line += f"  ${pnl/1000:>+11.1f}k"

        # Single-name default column
        jtd = r["jtd"]
        if abs(jtd) >= 1_000_000:
            jtd_str = f"${jtd/1e6:>+11.2f}M"
        else:
            jtd_str = f"${jtd/1000:>+11.1f}k"

        if r["direction"] == "SHORT":
            line += f"  {jtd_str:>14}  {'--':>14}"
        else:
            line += f"  {'--':>14}  {jtd_str:>14}"
        print(line)

    # Total row
    print(f"  {'-'*22}", end="")
    for _ in SPREAD_BUMPS:
        print(f"  {'-'*12}", end="")
    print(f"  {'-'*14}  {'-'*14}")

    total_line = f"  {'PORTFOLIO TOTAL':<22}"
    for bump in SPREAD_BUMPS:
        t = portfolio["stress_totals"][bump]
        if abs(t) >= 1_000_000:
            total_line += f"  ${t/1e6:>+11.2f}M"
        else:
            total_line += f"  ${t/1000:>+11.1f}k"

    sd = portfolio["shorts_default_pnl"]
    ld = portfolio["longs_default_pnl"]
    if abs(sd) >= 1_000_000:
        total_line += f"  ${sd/1e6:>+12.2f}M"
    else:
        total_line += f"  ${sd/1000:>+12.1f}k"
    if abs(ld) >= 1_000_000:
        total_line += f"  ${ld/1e6:>+12.2f}M"
    else:
        total_line += f"  ${ld/1000:>+12.1f}k"
    print(total_line)

    # Stress as % of NAV
    print()
    print(f"  {'AS % OF NAV':<22}", end="")
    for bump in SPREAD_BUMPS:
        t = portfolio["stress_totals"][bump]
        pct = t / nav * 100
        print(f"  {pct:>+11.2f}%", end="")
    sd_pct = portfolio["shorts_default_pnl"] / nav * 100
    ld_pct = portfolio["longs_default_pnl"] / nav * 100
    print(f"  {sd_pct:>+13.2f}%  {ld_pct:>+13.2f}%")

    # --- Summary for pitch deck ---
    print()
    print("=" * W)
    print("  PITCH DECK SUMMARY (copy these numbers)")
    print("=" * W)
    print(f"    Net DV01:                ${portfolio['net_dv01']:>+,.0f}")
    print(f"    Gross CS01:              ${portfolio['gross_cs01']:>,.0f}")
    print(f"    Gross JTD:               ${portfolio['gross_jtd']:>,.0f}  "
          f"({portfolio['gross_jtd']/nav*100:.1f}% of NAV)")
    print(f"    Max Single-Name JTD:     ${portfolio['max_jtd']:>,.0f}  "
          f"({portfolio['max_jtd_pct_nav']:.1f}% of NAV)  "
          f"[{portfolio['max_jtd_name']}]")
    print(f"    Net Carry p.a.:          ${portfolio['net_carry']:>+,.0f}  "
          f"({portfolio['net_carry_bps_nav']:>+.0f}bp)")
    print()
    print(f"    Stress -50bp (rally):     ${portfolio['stress_totals'][-50]:>+,.0f}  "
          f"({portfolio['stress_totals'][-50]/nav*100:>+.2f}%)")
    print(f"    Stress +100bp (selloff):  ${portfolio['stress_totals'][100]:>+,.0f}  "
          f"({portfolio['stress_totals'][100]/nav*100:>+.2f}%)")
    print(f"    Stress +200bp (crisis):   ${portfolio['stress_totals'][200]:>+,.0f}  "
          f"({portfolio['stress_totals'][200]/nav*100:>+.2f}%)")
    print(f"    All shorts default:       ${portfolio['shorts_default_pnl']:>+,.0f}  "
          f"({portfolio['shorts_default_pnl']/nav*100:>+.2f}%)")
    print(f"    All longs default:        ${portfolio['longs_default_pnl']:>+,.0f}  "
          f"({portfolio['longs_default_pnl']/nav*100:>+.2f}%)")
    print()
    print("  Model: ISDA Standard CDS Model, 40% recovery, 5Y maturity, "
          "3% EUR risk-free rate")
    print("  DV01 sign: negative = lose when spreads widen (net short risk)")
    print("  Carry sign: positive = net premium income (net protection seller)")
    print("=" * W)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(
    name_risks: list[dict],
    portfolio: dict,
    output_path: str,
    nav: float,
):
    """Export per-name risk metrics and portfolio summary to CSV."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "Name", "Direction", "Size_pct", "Notional_M", "Spread_bps",
        "DV01", "Signed_DV01", "CS01", "JTD", "RPV01",
        "Carry_pa", "PD_5Y",
    ]
    for bump in SPREAD_BUMPS:
        fieldnames.append(f"StressPnL_{bump:+d}bp")

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in name_risks:
            row = {
                "Name": r["name"],
                "Direction": r["direction"],
                "Size_pct": f"{r['size_pct']:.1f}",
                "Notional_M": f"{r['notional']/1e6:.1f}",
                "Spread_bps": f"{r['spread_bps']:.0f}",
                "DV01": f"{r['dv01']:.0f}",
                "Signed_DV01": f"{r['signed_dv01']:+.0f}",
                "CS01": f"{r['cs01']:.0f}",
                "JTD": f"{r['jtd']:+.0f}",
                "RPV01": f"{r['rpv01']:.4f}",
                "Carry_pa": f"{r['signed_carry']:+.0f}",
                "PD_5Y": f"{r['pd_5y']:.2%}",
            }
            for bump in SPREAD_BUMPS:
                row[f"StressPnL_{bump:+d}bp"] = f"{r['stress_pnl'][bump]:+.0f}"
            writer.writerow(row)

        # Summary row
        summary = {
            "Name": "PORTFOLIO TOTAL",
            "Direction": "NET SHORT",
            "Size_pct": "32.0",
            "Notional_M": f"{portfolio['gross_notional']/1e6:.1f}",
            "Spread_bps": "",
            "DV01": f"{sum(r['dv01'] for r in name_risks):.0f}",
            "Signed_DV01": f"{portfolio['net_dv01']:+.0f}",
            "CS01": f"{portfolio['gross_cs01']:.0f}",
            "JTD": f"{portfolio['gross_jtd']:.0f}",
            "RPV01": "",
            "Carry_pa": f"{portfolio['net_carry']:+.0f}",
            "PD_5Y": "",
        }
        for bump in SPREAD_BUMPS:
            summary[f"StressPnL_{bump:+d}bp"] = f"{portfolio['stress_totals'][bump]:+.0f}"
        writer.writerow(summary)

    print(f"\n  CSV saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Strategies in Credit — Portfolio Risk Metrics for Pitch Deck"
    )
    parser.add_argument(
        "--csv", type=str, default="outputs/portfolio_risk_metrics.csv",
        help="Output CSV path (default: outputs/portfolio_risk_metrics.csv)",
    )
    args = parser.parse_args()

    print("\n  Computing per-name risk metrics...", flush=True)
    name_risks = compute_name_risks(POSITIONS, NAV)

    print("  Aggregating portfolio metrics...", flush=True)
    portfolio = aggregate_portfolio(name_risks, NAV)

    print_report(name_risks, portfolio, NAV)
    export_csv(name_risks, portfolio, args.csv, NAV)


if __name__ == "__main__":
    main()
