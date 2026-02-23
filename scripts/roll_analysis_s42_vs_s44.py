"""
Roll Analysis: iTraxx S42 vs S44 — Base Correlation Comparison
==============================================================

Calibrates all 16 tranches (4 Xover + 4 Main, each for S42 and S44),
then computes side-by-side comparisons of base correlation, EL%, fair
spread, and CS01 changes.  Finally estimates roll P&L: what happens
if you hold an S42 tranche position and the market moves to S44 levels.

Market data:
  Xover S44: ref 250bp, 500bp running on all tranches
  Xover S42: ref 250bp, 500bp running on all tranches
  Main  S44: ref  53bp, 100bp running on all tranches
  Main  S42: ref  42bp, 100bp running on all tranches
"""
import sys
sys.path.insert(0, ".")

from analytics.tranche_pricer import (
    gaussian_copula_base_correlation, price_tranche,
    _protection_leg_tranche, _risky_annuity_tranche,
    ISDA_RECOVERY,
)


# ===================================================================
# Market Data — all 4 index/series combinations
# ===================================================================

XOVER_S44 = {
    "label": "Xover S44",
    "index": 250.0,
    "running": 500,
    "tranches": [
        {"name": "0-10% Equity",     "att": 0.00, "det": 0.10, "quote":  43.0,   "is_upfront": True},
        {"name": "10-20% Mezzanine", "att": 0.10, "det": 0.20, "quote":  -2.9,   "is_upfront": True},
        {"name": "20-35% Senior",    "att": 0.20, "det": 0.35, "quote": -13.45,  "is_upfront": True},
        {"name": "35-100% Super Sr", "att": 0.35, "det": 1.00, "quote": -19.3,   "is_upfront": True},   # 72bp conv -> -19.3% UF
    ],
}

XOVER_S42 = {
    "label": "Xover S42",
    "index": 250.0,
    "running": 500,
    "tranches": [
        {"name": "0-10% Equity",     "att": 0.00, "det": 0.10, "quote":  47.9,   "is_upfront": True},
        {"name": "10-20% Mezzanine", "att": 0.10, "det": 0.20, "quote":  -5.35,  "is_upfront": True},
        {"name": "20-35% Senior",    "att": 0.20, "det": 0.35, "quote": -13.35,  "is_upfront": True},
        {"name": "35-100% Super Sr", "att": 0.35, "det": 1.00, "quote":  47.9,   "is_upfront": False},  # 47.9bp conv
    ],
}

MAIN_S44 = {
    "label": "Main S44",
    "index": 53.0,
    "running": 100,
    "tranches": [
        {"name": "0-3% Equity",      "att": 0.00, "det": 0.03, "quote": 23.75,  "is_upfront": True},
        {"name": "3-6% Mezzanine",   "att": 0.03, "det": 0.06, "quote":  3.4,   "is_upfront": True},
        {"name": "6-12% Senior",     "att": 0.06, "det": 0.12, "quote": 95.3,   "is_upfront": False},   # 95.3bp conv
        {"name": "12-100% Super Sr", "att": 0.12, "det": 1.00, "quote": 27.0,   "is_upfront": False},   # 27bp conv
    ],
}

MAIN_S42 = {
    "label": "Main S42",
    "index": 42.0,
    "running": 100,
    "tranches": [
        {"name": "0-3% Equity",      "att": 0.00, "det": 0.03, "quote": 17.3,   "is_upfront": True},
        {"name": "3-6% Mezzanine",   "att": 0.03, "det": 0.06, "quote":  1.24,  "is_upfront": True},
        {"name": "6-12% Senior",     "att": 0.06, "det": 0.12, "quote": 67.3,   "is_upfront": False},   # 67.3bp conv
        {"name": "12-100% Super Sr", "att": 0.12, "det": 1.00, "quote": 19.5,   "is_upfront": False},   # 19.5bp conv
    ],
}

NOTIONAL = 10_000_000   # EUR 10M per tranche


# ===================================================================
# Helper: calibrate one full dataset and return dict of results
# ===================================================================

def calibrate_dataset(ds):
    """Calibrate all tranches for a dataset.  Returns list of dicts with
    rho, analytics, and model verification info for each tranche."""
    results = []
    for t in ds["tranches"]:
        rho = gaussian_copula_base_correlation(
            tranche_spread=t["quote"],
            attachment=t["att"],
            detachment=t["det"],
            index_spread=ds["index"],
            is_upfront=t["is_upfront"],
            running_coupon=ds["running"],
        )
        rho = max(0.01, min(0.99, rho))

        a = price_tranche(
            t["att"], t["det"], ds["index"], rho,
            running_coupon_bps=ds["running"], notional=NOTIONAL,
        )

        # Model verification
        prot = _protection_leg_tranche(ds["index"], rho, t["att"], t["det"], ISDA_RECOVERY, 5.0)
        rpv01 = _risky_annuity_tranche(ds["index"], rho, t["att"], t["det"], ISDA_RECOVERY, 5.0)

        if t["is_upfront"]:
            model_val = (prot - ds["running"] / 10_000 * rpv01) * 100
        else:
            model_val = prot / rpv01 * 10_000 if rpv01 > 0 else 0

        results.append({
            "name":       t["name"],
            "att":        t["att"],
            "det":        t["det"],
            "quote":      t["quote"],
            "is_upfront": t["is_upfront"],
            "rho":        rho,
            "model_val":  model_val,
            "analytics":  a,
        })
    return results


def fmt_pnl(v):
    """Format a P&L value (EUR)."""
    if abs(v) >= 1_000_000:
        return f"EUR{v/1e6:>+8.2f}M"
    else:
        return f"EUR{v/1000:>+8.1f}k"


# ===================================================================
# 1. CALIBRATE ALL 16 TRANCHES
# ===================================================================

print("=" * 120)
print("  iTraxx ROLL ANALYSIS: S42 vs S44")
print("  Calibrating all 16 tranches (Crossover + Main, S42 + S44)")
print("=" * 120)

# Calibrate each dataset
xo44 = calibrate_dataset(XOVER_S44)
xo42 = calibrate_dataset(XOVER_S42)
mn44 = calibrate_dataset(MAIN_S44)
mn42 = calibrate_dataset(MAIN_S42)

# Print individual calibration results
for ds_label, ds_data, results in [
    (XOVER_S44["label"], XOVER_S44, xo44),
    (XOVER_S42["label"], XOVER_S42, xo42),
    (MAIN_S44["label"],  MAIN_S44,  mn44),
    (MAIN_S42["label"],  MAIN_S42,  mn42),
]:
    print(f"\n  --- {ds_label} (ref {ds_data['index']:.0f}bp, {ds_data['running']}bp running) ---")
    print(f"  {'Tranche':<24} {'Quote':>10} {'Model':>10} {'Base Corr':>10} {'EL%':>7} {'Fair Spd':>9} {'CS01/10M':>10}")
    print(f"  {'-'*24} {'-'*10} {'-'*10} {'-'*10} {'-'*7} {'-'*9} {'-'*10}")
    for r in results:
        if r["is_upfront"]:
            q_str = f"{r['quote']:>+7.2f}%"
            m_str = f"{r['model_val']:>+7.2f}%"
        else:
            q_str = f"{r['quote']:>7.1f}bp"
            m_str = f"{r['model_val']:>7.1f}bp"
        a = r["analytics"]
        print(f"  {r['name']:<24} {q_str:>10} {m_str:>10} "
              f"{r['rho']:>9.2%} {a.expected_loss_pct:>6.2f}% {a.fair_spread_bps:>8.0f}bp  ${a.cs01:>9,.0f}")


# ===================================================================
# 2. SIDE-BY-SIDE COMPARISON: CROSSOVER S42 vs S44
# ===================================================================

def print_comparison(label, s42_data, s44_data, s42_results, s44_results):
    """Print side-by-side comparison table for one index."""
    idx42 = s42_data["index"]
    idx44 = s44_data["index"]

    print(f"\n{'=' * 130}")
    print(f"  {label}: S42 vs S44 COMPARISON")
    print(f"  S42 ref: {idx42:.0f}bp  |  S44 ref: {idx44:.0f}bp  |  Index move: {idx44 - idx42:+.0f}bp")
    print("=" * 130)

    hdr = (f"  {'Tranche':<24}"
           f" {'rho S42':>8} {'rho S44':>8} {'d(rho)':>8}"
           f" {'EL% S42':>8} {'EL% S44':>8} {'d(EL%)':>8}"
           f" {'Spd S42':>9} {'Spd S44':>9} {'d(Spd)':>9}"
           f" {'CS01 S42':>10} {'CS01 S44':>10} {'d(CS01)':>10}")
    print(hdr)
    print(f"  {'-'*24}" + f" {'-'*8}" * 3 + f" {'-'*8}" * 3 + f" {'-'*9}" * 3 + f" {'-'*10}" * 3)

    for r42, r44 in zip(s42_results, s44_results):
        a42 = r42["analytics"]
        a44 = r44["analytics"]
        d_rho = r44["rho"] - r42["rho"]
        d_el  = a44.expected_loss_pct - a42.expected_loss_pct
        d_spd = a44.fair_spread_bps - a42.fair_spread_bps
        d_cs01 = a44.cs01 - a42.cs01

        print(f"  {r42['name']:<24}"
              f" {r42['rho']:>7.2%} {r44['rho']:>7.2%} {d_rho:>+7.2%}"
              f" {a42.expected_loss_pct:>7.2f}% {a44.expected_loss_pct:>7.2f}% {d_el:>+7.2f}%"
              f" {a42.fair_spread_bps:>8.0f}bp {a44.fair_spread_bps:>8.0f}bp {d_spd:>+8.0f}bp"
              f" ${a42.cs01:>9,.0f} ${a44.cs01:>9,.0f} ${d_cs01:>+9,.0f}")


print_comparison("iTraxx CROSSOVER", XOVER_S42, XOVER_S44, xo42, xo44)
print_comparison("iTraxx MAIN",      MAIN_S42,  MAIN_S44,  mn42, mn44)


# ===================================================================
# 3. BASE CORRELATION SURFACE COMPARISON
# ===================================================================

print(f"\n{'=' * 90}")
print("  BASE CORRELATION SURFACE: S42 vs S44")
print("=" * 90)

print(f"\n  {'Index':<12} {'Tranche':<24} {'S42':>8} {'S44':>8} {'Change':>8} {'Direction':>12}")
print(f"  {'-'*12} {'-'*24} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")

for idx_label, r42_list, r44_list in [
    ("Crossover", xo42, xo44),
    ("Main",      mn42, mn44),
]:
    for r42, r44 in zip(r42_list, r44_list):
        d = r44["rho"] - r42["rho"]
        direction = "HIGHER" if d > 0.001 else "LOWER" if d < -0.001 else "FLAT"
        print(f"  {idx_label:<12} {r42['name']:<24} {r42['rho']:>7.2%} {r44['rho']:>7.2%} {d:>+7.2%} {direction:>12}")

# Monotonicity check
for idx_label, results in [("Xover S42", xo42), ("Xover S44", xo44),
                            ("Main S42", mn42), ("Main S44", mn44)]:
    rhos = [r["rho"] for r in results]
    mono = "MONOTONIC" if rhos == sorted(rhos) else "NON-MONOTONIC (smile)"
    print(f"  {idx_label:<12} surface: {mono}")


# ===================================================================
# 4. ROLL P&L: HOLD S42, MARKET MOVES TO S44
# ===================================================================
# The roll P&L captures what happens when:
#   - You entered a tranche position at S42 levels (priced with S42 correlation)
#   - The market has now moved to S44 levels (priced with S44 correlation + new index)
# This is a combined effect of:
#   (a) index spread change (S42 -> S44 ref)
#   (b) base correlation change (S42 -> S44 calibrated rho)

def compute_roll_pnl(s42_data, s44_data, s42_results, s44_results, label):
    """Compute roll P&L for each tranche: hold S42 position, market moves to S44."""
    print(f"\n{'=' * 110}")
    print(f"  ROLL P&L: {label}")
    print(f"  Hold S42 tranche, market moves to S44 levels (per EUR 10M notional)")
    print(f"  Index: {s42_data['index']:.0f}bp -> {s44_data['index']:.0f}bp  |  Running: {s42_data['running']}bp")
    print("=" * 110)

    print(f"\n  {'Tranche':<24} {'Entry MTM':>12} {'Exit MTM':>12} {'Roll P&L':>12}"
          f" {'Spread Comp':>12} {'Corr Comp':>12} {'Notes':>20}")
    print(f"  {'-'*24} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*20}")

    roll_data = []
    for r42, r44 in zip(s42_results, s44_results):
        a42 = r42["analytics"]  # S42 entry: priced at S42 index + S42 rho
        a44 = r44["analytics"]  # S44 exit:  priced at S44 index + S44 rho

        # Full roll P&L: MTM difference
        roll_pnl = a44.mtm - a42.mtm

        # Decompose into spread component and correlation component:
        # (a) Spread-only: reprice S42 tranche at S44 index but same S42 rho
        a_spread_only = price_tranche(
            r42["att"], r42["det"], s44_data["index"], r42["rho"],
            running_coupon_bps=s42_data["running"], notional=NOTIONAL,
        )
        spread_component = a_spread_only.mtm - a42.mtm

        # (b) Correlation component: reprice at S44 index with S44 rho vs S42 rho
        corr_component = a44.mtm - a_spread_only.mtm

        # Determine if the roll is favorable for protection buyer
        if roll_pnl > 0:
            note = "BUYER GAINS"
        elif roll_pnl < -10_000:
            note = "BUYER LOSES"
        else:
            note = "~FLAT"

        roll_data.append({
            "name": r42["name"],
            "entry_mtm": a42.mtm,
            "exit_mtm": a44.mtm,
            "roll_pnl": roll_pnl,
            "spread_comp": spread_component,
            "corr_comp": corr_component,
            "note": note,
            # For relative value ranking
            "att": r42["att"],
            "det": r42["det"],
            "d_rho": r44["rho"] - r42["rho"],
            "d_el": a44.expected_loss_pct - a42.expected_loss_pct,
            "d_spd": a44.fair_spread_bps - a42.fair_spread_bps,
            "rho42": r42["rho"],
            "rho44": r44["rho"],
        })

        print(f"  {r42['name']:<24} {fmt_pnl(a42.mtm):>12} {fmt_pnl(a44.mtm):>12} {fmt_pnl(roll_pnl):>12}"
              f" {fmt_pnl(spread_component):>12} {fmt_pnl(corr_component):>12} {note:>20}")

    return roll_data


xo_roll = compute_roll_pnl(XOVER_S42, XOVER_S44, xo42, xo44, "iTraxx CROSSOVER")
mn_roll = compute_roll_pnl(MAIN_S42,  MAIN_S44,  mn42, mn44, "iTraxx MAIN")


# ===================================================================
# 5. BEST ROLL OPPORTUNITIES (RELATIVE VALUE)
# ===================================================================

print(f"\n{'=' * 120}")
print("  BEST ROLL OPPORTUNITIES — RELATIVE VALUE RANKING")
print("  (Sorted by absolute roll P&L per EUR 10M notional)")
print("=" * 120)

all_rolls = []
for r in xo_roll:
    r["index"] = "Crossover"
    all_rolls.append(r)
for r in mn_roll:
    r["index"] = "Main"
    all_rolls.append(r)

# Sort by absolute roll P&L (biggest movers first)
all_rolls.sort(key=lambda x: abs(x["roll_pnl"]), reverse=True)

print(f"\n  {'#':>3} {'Index':<12} {'Tranche':<24} {'Roll P&L':>12} {'Spread':>12} {'Corr':>12}"
      f" {'d(rho)':>8} {'d(EL%)':>8} {'d(Spd)':>9} {'Signal':>18}")
print(f"  {'-'*3} {'-'*12} {'-'*24} {'-'*12} {'-'*12} {'-'*12}"
      f" {'-'*8} {'-'*8} {'-'*9} {'-'*18}")

for i, r in enumerate(all_rolls, 1):
    # Signal interpretation
    if r["roll_pnl"] > 50_000:
        signal = "BUY PROT S44"
    elif r["roll_pnl"] < -50_000:
        signal = "SELL PROT S44"
    elif abs(r["d_rho"]) > 0.03:
        signal = "CORR SHIFT"
    else:
        signal = "MONITOR"

    print(f"  {i:>3} {r['index']:<12} {r['name']:<24} {fmt_pnl(r['roll_pnl']):>12} "
          f"{fmt_pnl(r['spread_comp']):>12} {fmt_pnl(r['corr_comp']):>12}"
          f" {r['d_rho']:>+7.2%} {r['d_el']:>+7.2f}% {r['d_spd']:>+8.0f}bp {signal:>18}")


# ===================================================================
# 6. ROLL TRADE IDEAS
# ===================================================================

print(f"\n{'=' * 120}")
print("  ROLL TRADE IDEAS")
print("=" * 120)

# Find most interesting trades
biggest_pnl = max(all_rolls, key=lambda x: abs(x["roll_pnl"]))
biggest_corr_shift = max(all_rolls, key=lambda x: abs(x["d_rho"]))
biggest_el_shift = max(all_rolls, key=lambda x: abs(x["d_el"]))

print(f"\n  1. BIGGEST P&L MOVER:")
print(f"     {biggest_pnl['index']} {biggest_pnl['name']}: Roll P&L = {fmt_pnl(biggest_pnl['roll_pnl'])}")
print(f"     Spread component: {fmt_pnl(biggest_pnl['spread_comp'])}  |  Corr component: {fmt_pnl(biggest_pnl['corr_comp'])}")
print(f"     rho: {biggest_pnl['rho42']:.2%} -> {biggest_pnl['rho44']:.2%}  |  d(EL): {biggest_pnl['d_el']:+.2f}%")

print(f"\n  2. BIGGEST CORRELATION SHIFT:")
print(f"     {biggest_corr_shift['index']} {biggest_corr_shift['name']}: d(rho) = {biggest_corr_shift['d_rho']:+.2%}")
print(f"     Roll P&L = {fmt_pnl(biggest_corr_shift['roll_pnl'])}")
if biggest_corr_shift["d_rho"] > 0:
    print(f"     Correlation INCREASED -> senior tranches benefit, equity tranches lose")
else:
    print(f"     Correlation DECREASED -> equity tranches benefit, senior tranches lose")

print(f"\n  3. BIGGEST EXPECTED LOSS SHIFT:")
print(f"     {biggest_el_shift['index']} {biggest_el_shift['name']}: d(EL) = {biggest_el_shift['d_el']:+.2f}%")
print(f"     Roll P&L = {fmt_pnl(biggest_el_shift['roll_pnl'])}")

# Cross-index relative value
print(f"\n  4. CROSS-INDEX RELATIVE VALUE:")
xo_equity_roll = next(r for r in all_rolls if r["index"] == "Crossover" and "Equity" in r["name"])
mn_equity_roll = next(r for r in all_rolls if r["index"] == "Main" and "Equity" in r["name"])
print(f"     Xover Equity roll P&L: {fmt_pnl(xo_equity_roll['roll_pnl'])} (d_rho={xo_equity_roll['d_rho']:+.2%})")
print(f"     Main  Equity roll P&L: {fmt_pnl(mn_equity_roll['roll_pnl'])} (d_rho={mn_equity_roll['d_rho']:+.2%})")
if abs(xo_equity_roll["roll_pnl"]) > abs(mn_equity_roll["roll_pnl"]):
    print(f"     -> Crossover equity shows more roll sensitivity")
else:
    print(f"     -> Main equity shows more roll sensitivity")


# ===================================================================
# 7. SCENARIO: SPREAD + CORR BUMP SENSITIVITY AROUND THE ROLL
# ===================================================================

print(f"\n{'=' * 120}")
print("  ROLL SENSITIVITY MATRIX: P&L under spread/correlation stress")
print("  (Protection BUYER P&L from S42 entry, per EUR 10M notional)")
print("=" * 120)

for idx_label, s42_data, s44_data, s42_results, s44_results in [
    ("CROSSOVER", XOVER_S42, XOVER_S44, xo42, xo44),
    ("MAIN",      MAIN_S42,  MAIN_S44,  mn42, mn44),
]:
    print(f"\n  --- {idx_label} ---")
    spread_bumps = [-25, -10, 0, +10, +25, +50]

    for r42, r44 in zip(s42_results, s44_results):
        entry_mtm = r42["analytics"].mtm  # S42 entry price

        print(f"\n  {r42['name']} (S42 rho={r42['rho']:.2%}, S44 rho={r44['rho']:.2%})")

        header = f"    {'Spread bump':>12}"
        for b in spread_bumps:
            header += f"  {b:+d}bp".rjust(11)
        print(header)

        # Row 1: P&L using S42 correlation (no corr change)
        row_s42 = f"    {'S42 corr':<12}"
        for b in spread_bumps:
            new_idx = max(1.0, s44_data["index"] + b)
            bumped = price_tranche(
                r42["att"], r42["det"], new_idx, r42["rho"],
                running_coupon_bps=s42_data["running"], notional=NOTIONAL,
            )
            pnl = bumped.mtm - entry_mtm
            row_s42 += f"  {fmt_pnl(pnl):>9}"
        print(row_s42)

        # Row 2: P&L using S44 correlation (full roll)
        row_s44 = f"    {'S44 corr':<12}"
        for b in spread_bumps:
            new_idx = max(1.0, s44_data["index"] + b)
            bumped = price_tranche(
                r42["att"], r42["det"], new_idx, r44["rho"],
                running_coupon_bps=s44_data["running"], notional=NOTIONAL,
            )
            pnl = bumped.mtm - entry_mtm
            row_s44 += f"  {fmt_pnl(pnl):>9}"
        print(row_s44)

        # Row 3: Corr component only (difference)
        row_diff = f"    {'Corr effect':<12}"
        for b in spread_bumps:
            new_idx = max(1.0, s44_data["index"] + b)
            bumped42 = price_tranche(
                r42["att"], r42["det"], new_idx, r42["rho"],
                running_coupon_bps=s42_data["running"], notional=NOTIONAL,
            )
            bumped44 = price_tranche(
                r42["att"], r42["det"], new_idx, r44["rho"],
                running_coupon_bps=s44_data["running"], notional=NOTIONAL,
            )
            diff = bumped44.mtm - bumped42.mtm
            row_diff += f"  {fmt_pnl(diff):>9}"
        print(row_diff)


# ===================================================================
# FOOTER
# ===================================================================

print(f"\n{'=' * 120}")
print("  Model: 1F Gaussian copula (LHP), ISDA 40% recovery, 3% risk-free, quarterly")
print("  All calibrations from dealer quotes.  Roll P&L assumes flat carry (no accrual).")
print("  Positive P&L = protection BUYER gains.  Negative P&L = protection SELLER gains.")
print("=" * 120)
