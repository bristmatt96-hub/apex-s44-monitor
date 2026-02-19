"""
ISDA Standard Model CDS Pricer

Implements the ISDA Standard CDS Model for pricing 5Y CDS contracts.
Uses flat hazard rate bootstrapping, quarterly premium payments, ACT/360
day count, and ISDA standard recovery assumption of 40% for senior unsecured.

Key functions:
    spread_to_upfront()          - Running spread -> points upfront
    upfront_to_spread()          - Points upfront -> running spread equivalent
    cds_dv01()                   - Dollar value of 1bp spread move
    cds_cs01()                   - Credit spread sensitivity (same as DV01 for CDS)
    jump_to_default()            - JTD loss/gain on immediate default
    price_cds()                  - Mark-to-market of existing CDS position
    implied_default_probability() - Extract cumulative PD from spread

Usage:
    python -m analytics.cds_pricer                              # Show all Xover names
    python -m analytics.cds_pricer --spread 500                 # Price single spread
    python -m analytics.cds_pricer --upfront 20.8               # Convert PU to spread
    python -m analytics.cds_pricer --verify                     # Verify vs market data
    python -m analytics.cds_pricer --name "INEOS Finance PLC"   # Price specific name
"""

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ISDA_RECOVERY = 0.40          # Standard senior unsecured recovery
COUPON_FREQUENCY = 4          # Quarterly payments
STANDARD_COUPON_BPS = 500     # HY standard running coupon (500bps)
IG_COUPON_BPS = 100           # IG standard running coupon (100bps)
DAY_COUNT = 360               # ACT/360


# ---------------------------------------------------------------------------
# Core ISDA Model Functions
# ---------------------------------------------------------------------------

def _hazard_rate(spread_bps: float, recovery: float = ISDA_RECOVERY) -> float:
    """Bootstrap flat hazard rate from CDS spread.

    Under the flat hazard rate model:
        h = s / (1 - R)
    where s = spread (as decimal), R = recovery rate.
    """
    s = spread_bps / 10_000  # bps to decimal
    return s / (1 - recovery)


def _survival_probability(
    hazard_rate: float, t: float
) -> float:
    """Probability of survival to time t under flat hazard rate."""
    return math.exp(-hazard_rate * t)


def _discount_factor(rate: float, t: float) -> float:
    """Continuous compounding discount factor."""
    return math.exp(-rate * t)


def _risky_annuity(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
) -> float:
    """Calculate the risky annuity (RPV01 / risky PV01).

    This is the present value of 1bp of premium paid quarterly,
    conditional on survival. Also called the "risky duration".

    RPV01 = sum over payment dates of:
        DF(t_i) * SP(t_i) * delta_t

    where DF = discount factor, SP = survival probability,
    delta_t = accrual period (quarterly = 0.25).
    """
    h = _hazard_rate(spread_bps, recovery)
    n_periods = int(maturity_years * COUPON_FREQUENCY)
    dt = 1.0 / COUPON_FREQUENCY  # 0.25 for quarterly

    rpv01 = 0.0
    for i in range(1, n_periods + 1):
        t = i * dt
        df = _discount_factor(risk_free_rate, t)
        sp = _survival_probability(h, t)
        rpv01 += df * sp * dt

    # Accrued interest on default (approximation: half-period accrual)
    # This accounts for the fact that if default occurs mid-period,
    # the protection buyer owes accrued premium
    for i in range(1, n_periods + 1):
        t_start = (i - 1) * dt
        t_end = i * dt
        t_mid = (t_start + t_end) / 2
        df_mid = _discount_factor(risk_free_rate, t_mid)
        sp_start = _survival_probability(h, t_start)
        sp_end = _survival_probability(h, t_end)
        default_prob = sp_start - sp_end
        rpv01 += df_mid * default_prob * (dt / 2)

    return rpv01


def _protection_leg_pv(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
) -> float:
    """Present value of the protection leg (per unit notional).

    PV_prot = (1 - R) * sum over periods of:
        DF(t_mid) * (SP(t_start) - SP(t_end))

    This represents the expected payout on default.
    """
    h = _hazard_rate(spread_bps, recovery)
    n_periods = int(maturity_years * COUPON_FREQUENCY)
    dt = 1.0 / COUPON_FREQUENCY

    pv = 0.0
    for i in range(1, n_periods + 1):
        t_start = (i - 1) * dt
        t_end = i * dt
        t_mid = (t_start + t_end) / 2
        df_mid = _discount_factor(risk_free_rate, t_mid)
        sp_start = _survival_probability(h, t_start)
        sp_end = _survival_probability(h, t_end)
        default_prob = sp_start - sp_end
        pv += df_mid * default_prob

    return (1 - recovery) * pv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def spread_to_upfront(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
    coupon_bps: float | None = None,
) -> float:
    """Convert running spread to points upfront (ISDA standard model).

    The upfront payment compensates for the difference between the
    market spread and the standard running coupon:

        Upfront = (Spread - Coupon) * RPV01

    Expressed as a percentage of notional (points upfront).

    Args:
        spread_bps: Market CDS spread in basis points
        recovery: Recovery rate (default 0.40)
        maturity_years: Contract maturity in years (default 5)
        risk_free_rate: Risk-free rate for discounting (default 0.03)
        coupon_bps: Running coupon in bps (auto-selects 500 for HY, 100 for IG)

    Returns:
        Points upfront as percentage (e.g. 20.8 means 20.8% of notional)
    """
    if coupon_bps is None:
        coupon_bps = STANDARD_COUPON_BPS if spread_bps >= 200 else IG_COUPON_BPS

    rpv01 = _risky_annuity(spread_bps, recovery, maturity_years, risk_free_rate)

    # ISDA standard: Upfront % = (Spread - Coupon) * RPV01
    # where spread/coupon are in decimal (bps / 10000), RPV01 is in years
    # Result is a fraction of notional, multiply by 100 for percentage points
    upfront_pct = (spread_bps - coupon_bps) / 10_000 * rpv01 * 100

    return upfront_pct


def upfront_to_spread(
    points_upfront: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
    coupon_bps: float = STANDARD_COUPON_BPS,
) -> float:
    """Convert points upfront to running spread equivalent.

    Uses Newton-Raphson iteration to find the spread that produces
    the given upfront amount.

    Args:
        points_upfront: Upfront payment as percentage (e.g. 20.8)
        recovery: Recovery rate (default 0.40)
        maturity_years: Contract maturity in years (default 5)
        risk_free_rate: Risk-free rate for discounting (default 0.03)
        coupon_bps: Running coupon in bps (default 500 for HY)

    Returns:
        Equivalent running spread in basis points
    """
    # Initial guess: upfront_pct = (spread - coupon)/10000 * rpv01 * 100
    # Rearrange: spread = coupon + upfront_pct / (rpv01 * 100) * 10000
    # Typical RPV01 ~ 4.0 for 5Y, so: spread ~ coupon + upfront_pct / 0.04
    guess = coupon_bps + points_upfront / 0.04

    for _ in range(100):
        pu = spread_to_upfront(guess, recovery, maturity_years, risk_free_rate, coupon_bps)
        err = pu - points_upfront

        if abs(err) < 0.001:  # converged to 0.001 points
            return guess

        # Numerical derivative
        bump = 1.0  # 1bp bump
        pu_up = spread_to_upfront(guess + bump, recovery, maturity_years, risk_free_rate, coupon_bps)
        deriv = (pu_up - pu) / bump

        if abs(deriv) < 1e-12:
            break

        guess -= err / deriv
        guess = max(1.0, guess)  # floor at 1bp

    return guess


def cds_dv01(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
    notional: float = 10_000_000,
) -> float:
    """Spread DV01: dollar change in CDS value for 1bp spread move.

    DV01 = Notional * RPV01 * 0.0001

    For a protection buyer (short risk), DV01 is positive
    (value increases when spreads widen).

    Args:
        spread_bps: Current market spread in basis points
        recovery: Recovery rate
        maturity_years: Contract maturity
        risk_free_rate: Risk-free rate
        notional: CDS notional amount

    Returns:
        Dollar value of 1bp spread widening (positive for protection buyer)
    """
    rpv01 = _risky_annuity(spread_bps, recovery, maturity_years, risk_free_rate)
    return notional * rpv01 / 10_000


def cds_cs01(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
    notional: float = 10_000_000,
) -> float:
    """Credit spread sensitivity (CS01).

    For single-name CDS, CS01 = DV01 (they are equivalent).
    Included for convention completeness.

    Returns:
        Dollar value of 1bp parallel shift in credit spread
    """
    return cds_dv01(spread_bps, recovery, maturity_years, risk_free_rate, notional)


def jump_to_default(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    notional: float = 10_000_000,
    is_protection_buyer: bool = True,
) -> float:
    """Jump-to-default: P&L on immediate credit event.

    Protection buyer receives (1 - R) * Notional and loses accrued premium.
    Protection seller pays (1 - R) * Notional.

    Approximation: ignores accrued premium (small relative to LGD).

    Args:
        spread_bps: Current spread (used for accrued premium estimate)
        recovery: Recovery rate
        notional: CDS notional
        is_protection_buyer: True if you own protection (short risk)

    Returns:
        JTD P&L in dollars (positive = gain, negative = loss)
    """
    lgd = (1 - recovery) * notional  # Loss given default payout

    # Approximate accrued premium: assume mid-quarter (0.125 years)
    accrued = notional * (spread_bps / 10_000) * 0.125

    if is_protection_buyer:
        # Receive LGD, pay accrued premium
        return lgd - accrued
    else:
        # Pay LGD, receive accrued premium
        return -(lgd - accrued)


def price_cds(
    trade_spread_bps: float,
    market_spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
    notional: float = 10_000_000,
    is_protection_buyer: bool = True,
) -> float:
    """Mark-to-market value of an existing CDS position.

    MTM = (Market Spread - Trade Spread) * RPV01 * Notional

    For a protection buyer who bought at trade_spread:
    - If market widens above trade_spread: positive MTM (profit)
    - If market tightens below trade_spread: negative MTM (loss)

    Args:
        trade_spread_bps: Spread at which position was entered
        market_spread_bps: Current market spread
        recovery: Recovery rate
        maturity_years: Remaining maturity
        risk_free_rate: Risk-free rate
        notional: CDS notional
        is_protection_buyer: True if you bought protection (short risk)

    Returns:
        Mark-to-market value in dollars
    """
    rpv01 = _risky_annuity(market_spread_bps, recovery, maturity_years, risk_free_rate)
    mtm = (market_spread_bps - trade_spread_bps) * rpv01 / 10_000 * notional

    if is_protection_buyer:
        return mtm   # Profit when spreads widen
    else:
        return -mtm  # Profit when spreads tighten


def implied_default_probability(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
) -> float:
    """Extract cumulative default probability from CDS spread.

    Under the flat hazard rate model:
        PD(T) = 1 - exp(-h * T)
    where h = spread / (1 - R)

    Args:
        spread_bps: CDS spread in basis points
        recovery: Recovery rate
        maturity_years: Time horizon

    Returns:
        Cumulative default probability (0 to 1)
    """
    h = _hazard_rate(spread_bps, recovery)
    return 1 - math.exp(-h * maturity_years)


def annualised_default_probability(
    spread_bps: float,
    recovery: float = ISDA_RECOVERY,
) -> float:
    """Annualised (1-year) default probability from CDS spread.

    Simple approximation: PD_annual ~ spread / (1 - R)

    Returns:
        1-year default probability (0 to 1)
    """
    return (spread_bps / 10_000) / (1 - recovery)


# ---------------------------------------------------------------------------
# Convenience: Full CDS Analytics
# ---------------------------------------------------------------------------

@dataclass
class CDSAnalytics:
    """Complete analytics for a CDS position."""

    entity_name: str
    spread_bps: float
    points_upfront: float          # Computed or from market
    market_points_upfront: float   # From market data (if available)
    rpv01: float                   # Risky PV01
    dv01: float                    # Dollar DV01 per $10M notional
    jtd_long: float                # JTD if protection buyer
    jtd_short: float               # JTD if protection seller
    cum_default_prob_5y: float     # 5Y cumulative PD
    annual_default_prob: float     # 1Y PD
    implied_recovery: float        # Implied recovery (if PU available)
    convention: str                # "Spread" or "Points Upfront"


def full_analytics(
    entity_name: str,
    spread_bps: float,
    market_pu: float | None = None,
    convention: str = "Spread",
    recovery: float = ISDA_RECOVERY,
    maturity_years: float = 5.0,
    risk_free_rate: float = 0.03,
    notional: float = 10_000_000,
) -> CDSAnalytics:
    """Compute full analytics suite for a single name."""
    computed_pu = spread_to_upfront(spread_bps, recovery, maturity_years, risk_free_rate)
    rpv01 = _risky_annuity(spread_bps, recovery, maturity_years, risk_free_rate)
    dv01 = cds_dv01(spread_bps, recovery, maturity_years, risk_free_rate, notional)
    jtd_buy = jump_to_default(spread_bps, recovery, notional, is_protection_buyer=True)
    jtd_sell = jump_to_default(spread_bps, recovery, notional, is_protection_buyer=False)
    pd_5y = implied_default_probability(spread_bps, recovery, maturity_years)
    pd_1y = annualised_default_probability(spread_bps, recovery)

    # If market PU is available, back-solve implied recovery
    implied_rec = recovery
    if market_pu is not None and spread_bps > 0:
        # Try to find recovery that matches market PU
        for r_try in [i / 100 for i in range(10, 80)]:
            try_pu = spread_to_upfront(spread_bps, r_try, maturity_years, risk_free_rate)
            if abs(try_pu - market_pu) < abs(
                spread_to_upfront(spread_bps, implied_rec, maturity_years, risk_free_rate) - market_pu
            ):
                implied_rec = r_try

    return CDSAnalytics(
        entity_name=entity_name,
        spread_bps=spread_bps,
        points_upfront=computed_pu,
        market_points_upfront=market_pu or 0.0,
        rpv01=rpv01,
        dv01=dv01,
        jtd_long=jtd_buy,
        jtd_short=jtd_sell,
        cum_default_prob_5y=pd_5y,
        annual_default_prob=pd_1y,
        implied_recovery=implied_rec,
        convention=convention,
    )


# ---------------------------------------------------------------------------
# Verification vs Market Data
# ---------------------------------------------------------------------------

def verify_market_data():
    """Verify pricer against real market data for PU names."""
    try:
        from data.market_data_loader import load_market_data
    except ImportError:
        print("  Cannot import market_data_loader", file=sys.stderr)
        return

    md = load_market_data(index="xover")
    pu_names = {
        name: data for name, data in md.items()
        if data.get("convention") == "Points Upfront" and data.get("spread") and data.get("points_upfront")
    }

    print("=" * 100)
    print("  CDS PRICER VERIFICATION vs BLOOMBERG MARKET DATA")
    print("=" * 100)
    print(f"\n  {'Entity':<35} {'Spread':>8} {'Mkt PU':>8} {'Mod PU':>8} {'Diff':>8} {'Impl R':>7} {'5Y PD':>7}")
    print("  " + "-" * 95)

    for name, data in sorted(pu_names.items(), key=lambda x: x[1]["spread"], reverse=True):
        spread = data["spread"]
        mkt_pu = data["points_upfront"]
        analytics = full_analytics(
            name, spread,
            market_pu=mkt_pu,
            convention="Points Upfront",
        )
        diff = analytics.points_upfront - mkt_pu
        print(f"  {name[:33]:<35} {spread:>7.1f} {mkt_pu:>7.2f} "
              f"{analytics.points_upfront:>7.2f} {diff:>+7.2f} "
              f"{analytics.implied_recovery:>6.0%} {analytics.cum_default_prob_5y:>6.1%}")

    print()
    print("  Note: Differences arise from:")
    print("    - Flat hazard rate vs market-implied term structure")
    print("    - Simplified quarterly schedule vs actual IMM dates")
    print("    - EUR risk-free rate assumption (3% flat vs actual OIS curve)")
    print("    - Recovery rate assumption (40% standard vs market-implied)")
    print("=" * 100)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ISDA Standard Model CDS Pricer")
    parser.add_argument(
        "--spread", type=float, default=None,
        help="Price a single CDS spread (bps)",
    )
    parser.add_argument(
        "--upfront", type=float, default=None,
        help="Convert points upfront to spread equivalent",
    )
    parser.add_argument(
        "--recovery", type=float, default=ISDA_RECOVERY,
        help=f"Recovery rate (default: {ISDA_RECOVERY})",
    )
    parser.add_argument(
        "--maturity", type=float, default=5.0,
        help="Maturity in years (default: 5.0)",
    )
    parser.add_argument(
        "--rate", type=float, default=0.03,
        help="Risk-free rate (default: 0.03)",
    )
    parser.add_argument(
        "--notional", type=float, default=10_000_000,
        help="Notional amount (default: 10,000,000)",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Price a specific Xover name from market data",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify pricer against Bloomberg market data",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Show analytics for all Xover names",
    )
    args = parser.parse_args()

    today = datetime.now().strftime("%d %B %Y %H:%M")

    if args.verify:
        verify_market_data()
        return

    if args.upfront is not None:
        spread = upfront_to_spread(
            args.upfront, args.recovery, args.maturity, args.rate
        )
        print(f"\n  Points Upfront: {args.upfront:.2f}%")
        print(f"  Equivalent Spread: {spread:.1f}bps")
        print(f"  Recovery: {args.recovery:.0%} | Maturity: {args.maturity:.1f}Y | Rate: {args.rate:.2%}")
        pd5 = implied_default_probability(spread, args.recovery, args.maturity)
        print(f"  Implied 5Y Default Prob: {pd5:.1%}")
        return

    if args.spread is not None:
        s = args.spread
        pu = spread_to_upfront(s, args.recovery, args.maturity, args.rate)
        rpv01 = _risky_annuity(s, args.recovery, args.maturity, args.rate)
        dv01 = cds_dv01(s, args.recovery, args.maturity, args.rate, args.notional)
        cs01 = cds_cs01(s, args.recovery, args.maturity, args.rate, args.notional)
        jtd_buy = jump_to_default(s, args.recovery, args.notional, True)
        jtd_sell = jump_to_default(s, args.recovery, args.notional, False)
        pd5 = implied_default_probability(s, args.recovery, args.maturity)
        pd1 = annualised_default_probability(s, args.recovery)

        not_str = f"${args.notional:,.0f}"

        print(f"\n  {'='*60}")
        print(f"  CDS ANALYTICS -- {s:.0f}bps")
        print(f"  {'='*60}")
        print(f"  Spread:              {s:.1f}bps")
        print(f"  Points Upfront:      {pu:.2f}%")
        print(f"  RPV01:               {rpv01:.4f}")
        print(f"  Notional:            {not_str}")
        print(f"  DV01:                ${dv01:,.0f}")
        print(f"  CS01:                ${cs01:,.0f}")
        print(f"  JTD (prot buyer):    ${jtd_buy:,.0f}")
        print(f"  JTD (prot seller):   ${jtd_sell:,.0f}")
        print(f"  5Y Cum Default Prob: {pd5:.1%}")
        print(f"  1Y Default Prob:     {pd1:.2%}")
        print(f"  Recovery:            {args.recovery:.0%}")
        print(f"  Maturity:            {args.maturity:.1f}Y")
        print(f"  Risk-free rate:      {args.rate:.2%}")
        print(f"  {'='*60}")
        return

    if args.name or args.all:
        try:
            from data.market_data_loader import load_market_data
        except ImportError:
            print("  Cannot import market_data_loader", file=sys.stderr)
            sys.exit(1)

        md = load_market_data(index="xover")

        if args.name:
            # Find matching name
            matches = {n: d for n, d in md.items() if args.name.lower() in n.lower()}
            if not matches:
                print(f"  No match for '{args.name}'", file=sys.stderr)
                sys.exit(1)
        else:
            matches = {n: d for n, d in md.items() if d.get("spread")}

        print("=" * 110)
        print(f"  CREDIT CATALYST -- CDS ANALYTICS  ({today})")
        print("=" * 110)
        print(f"\n  {'Entity':<35} {'Spread':>7} {'PU':>7} {'RPV01':>6} "
              f"{'DV01':>9} {'JTD Buy':>10} {'5Y PD':>6} {'1Y PD':>6}")
        print("  " + "-" * 105)

        for name, data in sorted(matches.items()):
            spread = data.get("spread")
            if not spread:
                continue
            mkt_pu = data.get("points_upfront")
            a = full_analytics(
                name, spread,
                market_pu=mkt_pu,
                convention=data.get("convention", "Spread"),
                notional=args.notional,
            )
            pu_str = f"{mkt_pu:.1f}" if mkt_pu else f"{a.points_upfront:.1f}"
            print(f"  {name[:33]:<35} {spread:>6.0f} {pu_str:>7} {a.rpv01:>6.3f} "
                  f"${a.dv01:>8,.0f} ${a.jtd_long:>9,.0f} "
                  f"{a.cum_default_prob_5y:>5.1%} {a.annual_default_prob:>5.2%}")

        print(f"\n  Notional: ${args.notional:,.0f} | Recovery: {args.recovery:.0%} | "
              f"Rate: {args.rate:.2%} | Maturity: {args.maturity:.1f}Y")
        print("=" * 110)
        return

    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()
