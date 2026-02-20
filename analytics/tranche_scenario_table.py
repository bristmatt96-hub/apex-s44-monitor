"""
Tranche Scenario P&L Table Generator — Strategies in Credit

Generates defensible P&L scenario analysis for iTraxx Xover AND iTraxx Main
capital structures across parallel spread bumps using the Gaussian copula pricer.

Xover S44 capital structure (pitch deck format):
    0-10%   Equity       (500bp running + upfront)
    0-10%   Equity P/O   (protection only, no running coupon)
    10-20%  Mezzanine
    20-35%  Senior
    35-100% Super Senior

Main S44 capital structure:
    0-3%    Equity       (100bp running + upfront)
    3-6%    Mezzanine
    6-12%   Senior
    12-100% Super Senior

Usage:
    python -m analytics.tranche_scenario_table                          # both indices
    python -m analytics.tranche_scenario_table --index xover            # Xover only
    python -m analytics.tranche_scenario_table --index main             # Main only
    python -m analytics.tranche_scenario_table --index main --main-spread 55
    python -m analytics.tranche_scenario_table --spread 300 --notional 25
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from analytics.tranche_pricer import (
    price_tranche,
    gaussian_copula_base_correlation,
    expected_tranche_loss,
    _implied_default_prob,
    _risky_annuity_tranche,
    _protection_leg_tranche,
    ISDA_RECOVERY,
    RISK_FREE_RATE,
    TrancheAnalytics,
)

# ---------------------------------------------------------------------------
# Custom capital structures for pitch deck
# ---------------------------------------------------------------------------

XOVER_TRANCHES = [
    {
        "name": "0-10% Equity",
        "attachment": 0.00,
        "detachment": 0.10,
        "coupon_bps": 500,
        "traded_upfront": True,
    },
    {
        "name": "0-10% Equity (P/O)",
        "attachment": 0.00,
        "detachment": 0.10,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
    {
        "name": "10-20% Mezzanine",
        "attachment": 0.10,
        "detachment": 0.20,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
    {
        "name": "20-35% Senior",
        "attachment": 0.20,
        "detachment": 0.35,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
    {
        "name": "35-100% Super Senior",
        "attachment": 0.35,
        "detachment": 1.00,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
]

# Legacy alias — keep backwards compat
PITCH_TRANCHES = XOVER_TRANCHES

MAIN_TRANCHES = [
    {
        "name": "0-3% Equity",
        "attachment": 0.00,
        "detachment": 0.03,
        "coupon_bps": 100,
        "traded_upfront": True,
    },
    {
        "name": "3-6% Mezzanine",
        "attachment": 0.03,
        "detachment": 0.06,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
    {
        "name": "6-12% Senior",
        "attachment": 0.06,
        "detachment": 0.12,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
    {
        "name": "12-100% Super Senior",
        "attachment": 0.12,
        "detachment": 1.00,
        "coupon_bps": 0,
        "traded_upfront": False,
    },
]

# Standard spread scenarios (bps bump from current)
DEFAULT_BUMPS = [-50, -25, 0, +25, +50, +100, +200]


# ---------------------------------------------------------------------------
# Fast MTM-only pricer (skips risk metric finite differences)
# ---------------------------------------------------------------------------

def _fast_mtm(
    attachment: float,
    detachment: float,
    index_spread: float,
    base_correlation: float,
    notional: float,
    running_coupon_bps: float = 0,
    recovery: float = ISDA_RECOVERY,
    maturity: float = 5.0,
) -> float:
    """Compute tranche MTM without the expensive risk metrics.

    This is ~5x faster than price_tranche() because it skips the
    finite-difference bumps for CS01, delta, and gamma.
    """
    prot_pv = _protection_leg_tranche(
        index_spread, base_correlation, attachment, detachment,
        recovery, maturity,
    )
    rpv01 = _risky_annuity_tranche(
        index_spread, base_correlation, attachment, detachment,
        recovery, maturity,
    )
    return prot_pv * notional - running_coupon_bps / 10_000 * rpv01 * notional


# ---------------------------------------------------------------------------
# Base correlation calibration
# ---------------------------------------------------------------------------

def calibrate_base_correlations(
    index_spread: float,
    tranches: list[dict] | None = None,
) -> dict[str, float]:
    """Calibrate base correlations for the given tranche structure.

    Supports both Xover (wide HY spreads) and Main (tight IG spreads).

    For HY/Xover (spread > 100bp):
        Equity correlation ~20-45%, monotonically increasing curve upward.

    For IG/Main (spread ≤ 100bp):
        Uses the "correlation smile" — equity at very high rho (~85-95%),
        mezzanine dips lower (~20-30%), then rises through senior to super.
        This matches observed IG tranche market behaviour (O'Kane 2008 ch.17).

    The P/O equity tranche reuses the same correlation as the standard
    equity tranche (same attachment/detachment, just different coupon).
    """
    if tranches is None:
        tranches = XOVER_TRANCHES

    print("  Calibrating base correlations...", end="", flush=True)

    # Identify the equity tranche (first non-P/O tranche with attachment=0)
    equity_tranche = None
    for t in tranches:
        if t["attachment"] == 0.0 and "(P/O)" not in t["name"]:
            equity_tranche = t
            break

    if equity_tranche is None:
        raise ValueError("No equity tranche found in tranche list")

    equity_detach = equity_tranche["detachment"]
    equity_coupon = equity_tranche["coupon_bps"]
    is_ig = index_spread <= 100  # IG vs HY regime

    # --- Equity tranche correlation ---
    if is_ig:
        # IG regime: thin equity tranche requires high correlation to match
        # even modest upfront. Typical 0-3% equity at 50bp → rho ~85-95%.
        # Use ~4% upfront (market standard for Main at tight spreads).
        equity_upfront_guess = max(1.0, 2.0 + (index_spread - 30) * 0.08)
    elif index_spread <= 200:
        equity_upfront_guess = 8.0
    elif index_spread <= 300:
        equity_upfront_guess = 12.0 + (index_spread - 200) * 0.08
    elif index_spread <= 400:
        equity_upfront_guess = 20.0 + (index_spread - 300) * 0.10
    else:
        equity_upfront_guess = 30.0 + (index_spread - 400) * 0.05

    try:
        rho_equity = gaussian_copula_base_correlation(
            tranche_spread=equity_upfront_guess,
            attachment=0.00,
            detachment=equity_detach,
            index_spread=index_spread,
            is_upfront=True,
            running_coupon=equity_coupon,
        )
    except Exception:
        rho_equity = 0.85 if is_ig else 0.20  # regime-appropriate fallback

    # Clamp to regime-appropriate range
    if is_ig:
        rho_equity = max(0.60, min(0.98, rho_equity))
    else:
        rho_equity = max(0.05, min(0.45, rho_equity))

    # --- Build correlation dict for each tranche ---
    # Separate equity and non-equity tranches (excluding P/O)
    non_equity = [
        t for t in tranches
        if t["attachment"] > 0.0 and "(P/O)" not in t["name"]
    ]
    non_equity.sort(key=lambda t: t["attachment"])

    if is_ig:
        # IG "correlation smile" (O'Kane 2008, ch.17):
        # Equity very high, mezz dips low, senior rises, super rises more.
        # Typical Main base correlations at ~50bp:
        #   0-3%:   ~90-95%  (equity)
        #   3-6%:   ~20-30%  (mezzanine — the "smile" trough)
        #   6-12%:  ~40-55%  (senior — rising)
        #   12-100%: ~65-80% (super senior — approaches equity)
        ig_targets = [
            0.25,   # 1st mezz  — smile trough
            0.48,   # senior    — rising
            0.72,   # super senior — high
            0.82,   # extra (if >3 non-equity)
        ]
        result = {}
        for t in tranches:
            name = t["name"]
            if "(P/O)" in name:
                result[name] = round(rho_equity, 4)
                continue
            if t["attachment"] == 0.0:
                result[name] = round(rho_equity, 4)
                continue
            rank = next(
                (i for i, ne in enumerate(non_equity) if ne["name"] == name),
                len(non_equity) - 1,
            )
            rank = min(rank, len(ig_targets) - 1)
            result[name] = round(ig_targets[rank], 4)
    else:
        # HY monotonic curve: equity lowest, increasing through super senior
        # Interpolation targets: (rho_ceiling, blend_factor)
        seniority_targets = [
            (0.50, 0.55),   # 1st mezz
            (0.65, 0.70),   # senior
            (0.78, 0.85),   # super senior
            (0.85, 0.90),   # extra super senior
        ]
        result = {}
        for t in tranches:
            name = t["name"]
            if "(P/O)" in name:
                result[name] = round(rho_equity, 4)
                continue
            if t["attachment"] == 0.0:
                result[name] = round(rho_equity, 4)
                continue
            rank = next(
                (i for i, ne in enumerate(non_equity) if ne["name"] == name),
                len(non_equity) - 1,
            )
            rank = min(rank, len(seniority_targets) - 1)
            ceiling, blend = seniority_targets[rank]
            rho = rho_equity + (ceiling - rho_equity) * blend
            result[name] = round(rho, 4)

    print(" done.")
    for name, rho in result.items():
        print(f"    {name:<26} rho = {rho:.2%}")

    return result


# ---------------------------------------------------------------------------
# Scenario analysis
# ---------------------------------------------------------------------------

def generate_scenario_table(
    index_spread: float = 253.0,
    notional: float = 10_000_000,
    bumps: list[float] | None = None,
    tranches: list[dict] | None = None,
    index_name: str = "iTraxx Xover S44",
) -> tuple[list[tuple[dict, TrancheAnalytics]], list[dict]]:
    """Generate the full scenario P&L table.

    Prices base case with full analytics (for CS01/delta/gamma), then uses
    the fast MTM-only pricer for each scenario bump.

    Returns:
        (base_analytics, scenario_rows)
    """
    if bumps is None:
        bumps = DEFAULT_BUMPS
    if tranches is None:
        tranches = XOVER_TRANCHES

    print(f"\n{'='*60}")
    print(f"  Generating table for {index_name} @ {index_spread:.0f}bp")
    print(f"{'='*60}")

    correlations = calibrate_base_correlations(index_spread, tranches)

    # Price each tranche at base case (full analytics — slower but only N calls)
    print(f"\n  Pricing base case (full analytics)...", flush=True)
    base_analytics: list[tuple[dict, TrancheAnalytics]] = []
    for tranche in tranches:
        rho = correlations[tranche["name"]]
        print(f"    {tranche['name']}...", end="", flush=True)
        analytics = price_tranche(
            attachment=tranche["attachment"],
            detachment=tranche["detachment"],
            index_spread=index_spread,
            base_correlation=rho,
            notional=notional,
            running_coupon_bps=tranche["coupon_bps"],
        )
        base_analytics.append((tranche, analytics))
        print(f" EL={analytics.expected_loss_pct:.2f}%, "
              f"spread={analytics.fair_spread_bps:.0f}bp, "
              f"CS01=${analytics.cs01:,.0f}")

    # Compute scenario P&L using fast MTM-only pricer
    n_scenarios = len(bumps) - 1  # -1 because flat = base case
    print(f"\n  Computing {len(tranches)} x {n_scenarios} "
          f"scenario reprices...", end="", flush=True)

    scenario_rows = []
    for tranche, base_a in base_analytics:
        rho = correlations[tranche["name"]]
        row = {
            "tranche": tranche["name"],
            "attachment": tranche["attachment"],
            "detachment": tranche["detachment"],
            "base_correlation": rho,
            "fair_spread_bps": base_a.fair_spread_bps,
            "upfront_pct": base_a.upfront_pct,
            "expected_loss_pct": base_a.expected_loss_pct,
            "cs01": base_a.cs01,
            "delta": base_a.delta,
            "gamma": base_a.gamma,
            "leverage": base_a.leverage,
            "pnl": {},
        }

        base_mtm = base_a.mtm

        for bump in bumps:
            if bump == 0:
                row["pnl"][bump] = 0.0
                continue

            scenario_spread = max(1.0, index_spread + bump)
            bumped_mtm = _fast_mtm(
                attachment=tranche["attachment"],
                detachment=tranche["detachment"],
                index_spread=scenario_spread,
                base_correlation=rho,
                notional=notional,
                running_coupon_bps=tranche["coupon_bps"],
            )
            # P&L for a protection seller (long risk):
            # seller receives premium, pays on default
            # When spreads widen, protection value increases → loss for seller
            pnl = -(bumped_mtm - base_mtm)
            row["pnl"][bump] = round(pnl, 2)

        scenario_rows.append(row)

    print(" done.")
    return base_analytics, scenario_rows


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_table(
    index_spread: float,
    base_analytics: list[tuple[dict, TrancheAnalytics]],
    scenario_rows: list[dict],
    bumps: list[float],
    notional: float,
    index_name: str = "iTraxx Xover S44",
):
    """Print the scenario table to terminal."""
    W = 115
    today = datetime.now().strftime("%Y-%m-%d")
    pd = _implied_default_prob(index_spread, ISDA_RECOVERY, 5.0)

    print()
    print("=" * W)
    print(f"  STRATEGIES IN CREDIT — Tranche Scenario Analysis — {index_name}")
    print(f"  {today}")
    print("=" * W)
    print(f"  Index Spread:   {index_spread:.0f}bp ({index_name})")
    print(f"  Recovery:       {ISDA_RECOVERY:.0%}  |  Maturity: 5Y  |  "
          f"Notional: €{notional/1e6:.0f}M per tranche")
    print(f"  Implied 5Y PD:  {pd:.2%}  |  "
          f"Expected Loss:  {pd*(1-ISDA_RECOVERY):.2%}")

    # Base case analytics
    print()
    print("  BASE CASE ANALYTICS")
    print("  " + "-" * (W - 4))
    print(f"  {'Tranche':<26} {'Corr':>6} {'EL%':>6} {'Spread':>8} "
          f"{'Upfront':>10} {'CS01':>10} {'Delta':>7} {'Leverage':>9}")
    print(f"  {'-'*26} {'-'*6} {'-'*6} {'-'*8} {'-'*10} "
          f"{'-'*10} {'-'*7} {'-'*9}")

    for row in scenario_rows:
        # Determine upfront display based on tranche type
        if row["upfront_pct"] and row["upfront_pct"] != 0:
            # Find the coupon for this tranche
            coupon = 0
            for t, _ in base_analytics:
                if t["name"] == row["tranche"]:
                    coupon = t["coupon_bps"]
                    break
            if coupon > 0:
                uf_str = f"{row['upfront_pct']:.1f}%+{coupon}"
            else:
                uf_str = f"{row['upfront_pct']:.1f}%"
        else:
            uf_str = "--"
        print(f"  {row['tranche']:<26} {row['base_correlation']:>5.1%} "
              f"{row['expected_loss_pct']:>5.1f}% {row['fair_spread_bps']:>7.0f}bp "
              f"{uf_str:>10} €{row['cs01']:>9,.0f} {row['delta']:>6.2f} "
              f"{row['leverage']:>8.1f}x")

    # Scenario P&L table
    print()
    print("  P&L BY SPREAD SCENARIO (€, long risk / protection seller)")
    print("  " + "-" * (W - 4))

    # Header row with bump labels
    header = f"  {'Tranche':<26}"
    for b in bumps:
        header += f"  {b:+.0f}bp".rjust(12)
    print(header)

    # Sub-header with absolute spread levels
    sub = f"  {'':26}"
    for b in bumps:
        spread = max(1.0, index_spread + b)
        sub += f"  ({spread:.0f})".rjust(12)
    print(sub)

    print(f"  {'-'*26}  " + "  ".join(["-" * 10] * len(bumps)))

    # Per-tranche rows
    total_by_bump = {b: 0.0 for b in bumps}
    for row in scenario_rows:
        line = f"  {row['tranche']:<26}"
        for b in bumps:
            pnl = row["pnl"][b]
            total_by_bump[b] += pnl
            if abs(pnl) >= 1_000_000:
                line += f"  €{pnl/1e6:>+9,.2f}M"
            else:
                line += f"  €{pnl/1000:>+9,.1f}k"
        print(line)

    # Total row
    print(f"  {'-'*26}  " + "  ".join(["-" * 10] * len(bumps)))
    total_line = f"  {'TOTAL (all tranches)':<26}"
    for b in bumps:
        t = total_by_bump[b]
        if abs(t) >= 1_000_000:
            total_line += f"  €{t/1e6:>+9,.2f}M"
        else:
            total_line += f"  €{t/1000:>+9,.1f}k"
    print(total_line)

    # Convexity check
    print()
    print("  CONVEXITY CHECK (ratio of P&L moves):")
    for row in scenario_rows:
        pnl = row["pnl"]
        if 50 in pnl and 100 in pnl and pnl[50] != 0:
            r1 = pnl[100] / pnl[50]
            label = ("convex" if abs(r1) > 2.0
                     else "linear" if abs(r1) > 1.8
                     else "sub-linear")
            print(f"    {row['tranche']:<26} "
                  f"+100bp/+50bp = {r1:>+.2f}x  ({label})")

    print()
    print("=" * W)
    print("  Model: One-factor Gaussian copula (LHP), ISDA 40% recovery, "
          "flat term structure, 3% risk-free rate")
    print("  Base correlations calibrated from equity upfront "
          "with standard curve interpolation (O'Kane 2008)")
    print("=" * W)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(
    scenario_rows: list[dict],
    bumps: list[float],
    index_spread: float,
    output_path: str,
    index_name: str = "iTraxx Xover S44",
):
    """Export scenario table to CSV."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "Index", "Tranche", "Attachment", "Detachment", "BaseCorrelation",
        "FairSpread_bps", "Upfront_pct", "ExpectedLoss_pct",
        "CS01_eur", "Delta", "Gamma", "Leverage",
    ]
    for b in bumps:
        spread = max(1.0, index_spread + b)
        fieldnames.append(f"PnL_{b:+d}bp_({spread:.0f})")

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in scenario_rows:
            csv_row = {
                "Index": index_name,
                "Tranche": row["tranche"],
                "Attachment": f"{row['attachment']:.0%}",
                "Detachment": f"{row['detachment']:.0%}",
                "BaseCorrelation": f"{row['base_correlation']:.2%}",
                "FairSpread_bps": f"{row['fair_spread_bps']:.0f}",
                "Upfront_pct": f"{row['upfront_pct']:.2f}" if row["upfront_pct"] else "",
                "ExpectedLoss_pct": f"{row['expected_loss_pct']:.2f}",
                "CS01_eur": f"{row['cs01']:.0f}",
                "Delta": f"{row['delta']:.2f}",
                "Gamma": f"{row['gamma']:.4f}",
                "Leverage": f"{row['leverage']:.1f}",
            }
            for b in bumps:
                spread = max(1.0, index_spread + b)
                csv_row[f"PnL_{b:+d}bp_({spread:.0f})"] = f"{row['pnl'][b]:.0f}"
            writer.writerow(csv_row)

    print(f"\n  CSV saved to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Strategies in Credit — Tranche Scenario P&L Table"
    )
    parser.add_argument(
        "--index", choices=["xover", "main", "both"], default="both",
        help="Which index to run (default: both)",
    )
    parser.add_argument(
        "--spread", type=float, default=253.0,
        help="Current iTraxx Xover index spread in bps (default: 253)",
    )
    parser.add_argument(
        "--main-spread", type=float, default=50.0,
        help="Current iTraxx Main index spread in bps (default: 50)",
    )
    parser.add_argument(
        "--notional", type=float, default=10.0,
        help="Notional per tranche in €M (default: 10)",
    )
    parser.add_argument(
        "--csv-dir", type=str, default="outputs",
        help="Output directory for CSVs (default: outputs)",
    )
    args = parser.parse_args()

    notional = args.notional * 1_000_000
    bumps = DEFAULT_BUMPS

    run_xover = args.index in ("xover", "both")
    run_main = args.index in ("main", "both")

    # --- Xover ---
    if run_xover:
        xover_base, xover_rows = generate_scenario_table(
            index_spread=args.spread,
            notional=notional,
            bumps=bumps,
            tranches=XOVER_TRANCHES,
            index_name="iTraxx Xover S44",
        )
        print_table(
            args.spread, xover_base, xover_rows, bumps, notional,
            index_name="iTraxx Xover S44",
        )
        xover_csv = str(Path(args.csv_dir) / "tranche_scenarios_xover.csv")
        export_csv(
            xover_rows, bumps, args.spread, xover_csv,
            index_name="iTraxx Xover S44",
        )

    # --- Main ---
    if run_main:
        main_base, main_rows = generate_scenario_table(
            index_spread=args.main_spread,
            notional=notional,
            bumps=bumps,
            tranches=MAIN_TRANCHES,
            index_name="iTraxx Main S44",
        )
        print_table(
            args.main_spread, main_base, main_rows, bumps, notional,
            index_name="iTraxx Main S44",
        )
        main_csv = str(Path(args.csv_dir) / "tranche_scenarios_main.csv")
        export_csv(
            main_rows, bumps, args.main_spread, main_csv,
            index_name="iTraxx Main S44",
        )


if __name__ == "__main__":
    main()
