"""Calibrate Gaussian copula to real Xover S44 dealer quotes."""
import sys
sys.path.insert(0, ".")

from analytics.tranche_pricer import (
    gaussian_copula_base_correlation, price_tranche,
    _protection_leg_tranche, _risky_annuity_tranche,
    ISDA_RECOVERY,
)

INDEX = 250.0   # Xover S44 ref
RUNNING = 500   # 5% running coupon on all tranches

# Real dealer quotes — Xover S44
MARKET = [
    {"name": "0-10% Equity",      "att": 0.00, "det": 0.10, "upfront":  43.0},
    {"name": "10-20% Mezzanine",  "att": 0.10, "det": 0.20, "upfront":  -2.9},
    {"name": "20-35% Senior",     "att": 0.20, "det": 0.35, "upfront": -13.45},
    {"name": "35-100% Super Sr",  "att": 0.35, "det": 1.00, "upfront": -19.3},  # 72bp conv
]

print("=" * 90)
print("  iTraxx CROSSOVER S44 — BASE CORRELATION CALIBRATION")
print(f"  Index: {INDEX:.0f}bp | Running: {RUNNING}bp on all tranches")
print("=" * 90)

hdr = f"  {'Tranche':<24} {'Mkt UF%':>8} {'Mod UF%':>8} {'Error':>8} {'Base Corr':>10} {'EL%':>7} {'Fair Spd':>9} {'CS01/10M':>10}"
print(f"\n{hdr}")
print(f"  {'-'*24} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*7} {'-'*9} {'-'*10}")

correlations = {}
for t in MARKET:
    rho = gaussian_copula_base_correlation(
        tranche_spread=t["upfront"],
        attachment=t["att"],
        detachment=t["det"],
        index_spread=INDEX,
        is_upfront=True,
        running_coupon=RUNNING,
    )
    rho = max(0.01, min(0.99, rho))
    correlations[t["name"]] = rho

    # Verify model upfront
    prot = _protection_leg_tranche(INDEX, rho, t["att"], t["det"], ISDA_RECOVERY, 5.0)
    rpv01 = _risky_annuity_tranche(INDEX, rho, t["att"], t["det"], ISDA_RECOVERY, 5.0)
    model_uf = (prot - RUNNING / 10_000 * rpv01) * 100

    a = price_tranche(t["att"], t["det"], INDEX, rho, running_coupon_bps=RUNNING, notional=10_000_000)
    err = model_uf - t["upfront"]
    print(f"  {t['name']:<24} {t['upfront']:>+7.2f}% {model_uf:>+7.2f}% {err:>+7.3f}% "
          f"{rho:>9.2%} {a.expected_loss_pct:>6.2f}% {a.fair_spread_bps:>8.0f}bp  ${a.cs01:>9,.0f}")

# Base correlation surface
print(f"\n  BASE CORRELATION SURFACE:")
print("  " + "-" * 50)
rhos = list(correlations.values())
for name, rho in correlations.items():
    print(f"    {name:<24} {rho:.4f}  ({rho:.1%})")

if rhos == sorted(rhos):
    print("  [OK] Monotonically increasing — standard HY shape")
else:
    print("  [NOTE] Non-monotonic — correlation smile detected")

# Scenario P&L
print(f"\n{'=' * 100}")
print("  SCENARIO P&L (per EUR 10M notional, protection BUYER = short risk)")
print("=" * 100)

bumps = [-50, -25, 0, +25, +50, +100, +200]

header = f"  {'Tranche':<24}"
for b in bumps:
    header += f"  {b:+d}bp".rjust(11)
print(header)

sub = f"  {'':24}"
for b in bumps:
    sub += f"  ({max(1, INDEX+b):.0f})".rjust(11)
print(sub)
print(f"  {'-'*24}  " + "  ".join(["-"*9] * len(bumps)))

total_by_bump = {b: 0.0 for b in bumps}
for t in MARKET:
    rho = correlations[t["name"]]
    base_a = price_tranche(t["att"], t["det"], INDEX, rho, running_coupon_bps=RUNNING, notional=10_000_000)
    base_mtm = base_a.mtm

    row = f"  {t['name']:<24}"
    for b in bumps:
        new_spread = max(1.0, INDEX + b)
        bumped = price_tranche(t["att"], t["det"], new_spread, rho, running_coupon_bps=RUNNING, notional=10_000_000)
        pnl = bumped.mtm - base_mtm
        total_by_bump[b] += pnl
        if abs(pnl) >= 1_000_000:
            row += f"  EUR{pnl/1e6:>+7.2f}M"
        else:
            row += f"  EUR{pnl/1000:>+7.1f}k"
    print(row)

print(f"  {'-'*24}  " + "  ".join(["-"*9] * len(bumps)))
total_row = f"  {'TOTAL':<24}"
for b in bumps:
    v = total_by_bump[b]
    if abs(v) >= 1_000_000:
        total_row += f"  EUR{v/1e6:>+7.2f}M"
    else:
        total_row += f"  EUR{v/1000:>+7.1f}k"
print(total_row)

# Convexity
print(f"\n  CONVEXITY CHECK:")
for t in MARKET:
    rho = correlations[t["name"]]
    base_mtm = price_tranche(t["att"], t["det"], INDEX, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm
    pnl_50 = price_tranche(t["att"], t["det"], INDEX+50, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm - base_mtm
    pnl_100 = price_tranche(t["att"], t["det"], INDEX+100, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm - base_mtm
    pnl_200 = price_tranche(t["att"], t["det"], INDEX+200, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm - base_mtm
    r1 = pnl_100 / pnl_50 if pnl_50 != 0 else 0
    r2 = pnl_200 / pnl_100 if pnl_100 != 0 else 0
    label = "CONVEX" if abs(r1) > 2.0 else "linear" if abs(r1) > 1.8 else "sub-linear"
    print(f"    {t['name']:<24} +100/+50 = {r1:>+.2f}x   +200/+100 = {r2:>+.2f}x   [{label}]")

print(f"\n{'=' * 100}")
print("  Model: 1F Gaussian copula (LHP), ISDA 40% recovery, 3% risk-free, quarterly")
print("  Calibrated from real Xover S44 dealer upfront quotes")
print("=" * 100)
