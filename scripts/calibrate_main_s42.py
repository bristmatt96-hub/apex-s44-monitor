"""Calibrate Gaussian copula to real iTraxx Main S42 dealer quotes."""
import sys
sys.path.insert(0, ".")

from analytics.tranche_pricer import (
    gaussian_copula_base_correlation, price_tranche,
    _protection_leg_tranche, _risky_annuity_tranche,
    ISDA_RECOVERY,
)

INDEX = 42.0    # Main S42 ref spread
RUNNING = 100   # 1% running coupon (100bp) on all tranches — ISDA IG standard

# Real dealer quotes — iTraxx Main S42
# Equity/Mezz: upfront %, Senior/Super Sr: conventional spread (bp)
MARKET = [
    {"name": "0-3% Equity",       "att": 0.00, "det": 0.03, "quote": 17.3,  "is_upfront": True},
    {"name": "3-6% Mezzanine",    "att": 0.03, "det": 0.06, "quote": 1.24,  "is_upfront": True},
    {"name": "6-12% Senior",      "att": 0.06, "det": 0.12, "quote": 67.3,  "is_upfront": False},  # 67.3bp conv
    {"name": "12-100% Super Sr",  "att": 0.12, "det": 1.00, "quote": 19.5,  "is_upfront": False},  # 19.5bp conv
]

print("=" * 90)
print("  iTraxx MAIN S42 — BASE CORRELATION CALIBRATION")
print(f"  Index: {INDEX:.0f}bp | Running: {RUNNING}bp on all tranches")
print("=" * 90)

hdr = f"  {'Tranche':<24} {'Mkt Quote':>10} {'Model':>10} {'Error':>8} {'Base Corr':>10} {'EL%':>7} {'Fair Spd':>9} {'CS01/10M':>10}"
print(f"\n{hdr}")
print(f"  {'-'*24} {'-'*10} {'-'*10} {'-'*8} {'-'*10} {'-'*7} {'-'*9} {'-'*10}")

correlations = {}
for t in MARKET:
    rho = gaussian_copula_base_correlation(
        tranche_spread=t["quote"],
        attachment=t["att"],
        detachment=t["det"],
        index_spread=INDEX,
        is_upfront=t["is_upfront"],
        running_coupon=RUNNING,
    )
    rho = max(0.01, min(0.99, rho))
    correlations[t["name"]] = rho

    # Verify model
    prot = _protection_leg_tranche(INDEX, rho, t["att"], t["det"], ISDA_RECOVERY, 5.0)
    rpv01 = _risky_annuity_tranche(INDEX, rho, t["att"], t["det"], ISDA_RECOVERY, 5.0)

    if t["is_upfront"]:
        model_val = (prot - RUNNING / 10_000 * rpv01) * 100
        err = model_val - t["quote"]
        mkt_str = f"{t['quote']:>+7.2f}%"
        mod_str = f"{model_val:>+7.2f}%"
        err_str = f"{err:>+7.3f}%"
    else:
        model_val = prot / rpv01 * 10_000 if rpv01 > 0 else 0
        err = model_val - t["quote"]
        mkt_str = f"{t['quote']:>7.1f}bp"
        mod_str = f"{model_val:>7.1f}bp"
        err_str = f"{err:>+7.3f}bp"

    a = price_tranche(t["att"], t["det"], INDEX, rho, running_coupon_bps=RUNNING, notional=10_000_000)
    print(f"  {t['name']:<24} {mkt_str:>10} {mod_str:>10} {err_str:>8} "
          f"{rho:>9.2%} {a.expected_loss_pct:>6.2f}% {a.fair_spread_bps:>8.0f}bp  ${a.cs01:>9,.0f}")

# Base correlation surface
print(f"\n  BASE CORRELATION SURFACE:")
print("  " + "-" * 50)
rhos = list(correlations.values())
for name, rho in correlations.items():
    print(f"    {name:<24} {rho:.4f}  ({rho:.1%})")

if rhos == sorted(rhos):
    print("  [OK] Monotonically increasing — standard IG shape")
else:
    print("  [NOTE] Non-monotonic — correlation smile detected")

# Scenario P&L
print(f"\n{'=' * 100}")
print("  SCENARIO P&L (per EUR 10M notional, protection BUYER = short risk)")
print("=" * 100)

bumps = [-20, -10, 0, +10, +20, +50, +100]

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
    pnl_20 = price_tranche(t["att"], t["det"], INDEX+20, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm - base_mtm
    pnl_50 = price_tranche(t["att"], t["det"], INDEX+50, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm - base_mtm
    pnl_100 = price_tranche(t["att"], t["det"], INDEX+100, rho, running_coupon_bps=RUNNING, notional=10_000_000).mtm - base_mtm
    r1 = pnl_50 / pnl_20 if pnl_20 != 0 else 0
    r2 = pnl_100 / pnl_50 if pnl_50 != 0 else 0
    label = "CONVEX" if abs(r1) > 2.5 else "linear" if abs(r1) > 2.3 else "sub-linear"
    print(f"    {t['name']:<24} +50/+20 = {r1:>+.2f}x   +100/+50 = {r2:>+.2f}x   [{label}]")

print(f"\n{'=' * 100}")
print("  Model: 1F Gaussian copula (LHP), ISDA 40% recovery, 3% risk-free, quarterly")
print("  Calibrated from real iTraxx Main S42 dealer quotes")
print("=" * 100)
