"""
High-Yield Maturity Wall & Refinancing Dashboard
Route: /maturity-wall

US HY & EUR HY maturity walls by rating, legacy coupon vs refi yield,
stress scenario refi yields, interest coverage ratio, BB-BBB spread gap
(fallen angel indicator), HY effective yield, and key metrics summary.
"""

import numpy as np
from datetime import datetime
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt

maturity_bp = Blueprint("maturity_wall", __name__)

# ---------------------------------------------------------------------------
# Maturity wall data
# ---------------------------------------------------------------------------
YEARS = list(range(2026, 2037))  # 2026-2036
N_YEARS = len(YEARS)

# Historical time series (2014-2026)
HIST_YEARS = list(range(2014, 2027))
N_HIST = len(HIST_YEARS)


def _generate_maturity_data():
    """Generate synthetic maturity wall and refinancing data."""
    np.random.seed(860)

    # --- US HY Maturity Wall by Rating ($B) ---
    us_bb = np.array([45, 65, 95, 130, 110, 85, 70, 55, 40, 30, 20], dtype=float)
    us_b = np.array([25, 40, 60, 80, 70, 55, 45, 35, 25, 18, 12], dtype=float)
    us_ccc = np.array([10, 15, 25, 35, 28, 20, 15, 10, 8, 5, 3], dtype=float)
    # Add noise
    us_bb += np.random.normal(0, 3, N_YEARS)
    us_b += np.random.normal(0, 2, N_YEARS)
    us_ccc += np.random.normal(0, 1, N_YEARS)
    us_bb = np.clip(us_bb, 5, 200)
    us_b = np.clip(us_b, 3, 120)
    us_ccc = np.clip(us_ccc, 1, 60)

    # --- EUR HY Maturity Wall by Rating ($B) ---
    eur_bb = us_bb * 0.3 + np.random.normal(0, 2, N_YEARS)
    eur_b = us_b * 0.28 + np.random.normal(0, 1, N_YEARS)
    eur_ccc = us_ccc * 0.25 + np.random.normal(0, 0.5, N_YEARS)
    eur_bb = np.clip(eur_bb, 2, 60)
    eur_b = np.clip(eur_b, 1, 40)
    eur_ccc = np.clip(eur_ccc, 0.5, 20)

    us_total = us_bb + us_b + us_ccc
    eur_total = eur_bb + eur_b + eur_ccc

    # --- Legacy Coupon vs Current Refi Yield ---
    legacy_coupon = np.array([4.5, 4.8, 5.0, 5.2, 5.5, 5.8, 6.0,
                              6.2, 6.5, 6.8, 7.0], dtype=float)
    legacy_coupon += np.random.normal(0, 0.2, N_YEARS)
    current_refi = np.array([7.5, 7.6, 7.4, 7.3, 7.2, 7.1, 7.0,
                              6.9, 6.8, 6.7, 6.6], dtype=float)
    current_refi += np.random.normal(0, 0.15, N_YEARS)

    # --- Stress Scenarios refi yield ---
    base_refi = current_refi.copy()
    rates_100 = base_refi + 1.0 + np.random.normal(0, 0.1, N_YEARS)
    spreads_200 = base_refi + 2.0 + np.random.normal(0, 0.15, N_YEARS)
    crisis_500 = base_refi + 5.0 + np.random.normal(0, 0.2, N_YEARS)

    # --- Interest Coverage Ratio (historical) ---
    icr = np.zeros(N_HIST)
    for i, y in enumerate(HIST_YEARS):
        icr[i] = 4.0
        # COVID dip
        icr[i] -= 2.0 * np.exp(-0.5 * ((y - 2020) / 0.5) ** 2)
        # Rate hiking pressure
        icr[i] -= 1.5 * np.exp(-0.5 * ((y - 2024) / 1.0) ** 2)
        # Recovery
        icr[i] += 1.0 * np.exp(-0.5 * ((y - 2017) / 2.0) ** 2)
    icr += np.random.normal(0, 0.2, N_HIST)
    icr = np.clip(icr, 1.0, 6.0)

    # --- BB-BBB Spread Gap (Fallen Angel Indicator) ---
    bb_bbb_gap = np.zeros(N_HIST)
    for i, y in enumerate(HIST_YEARS):
        bb_bbb_gap[i] = 120
        bb_bbb_gap[i] += 100 * np.exp(-0.5 * ((y - 2016) / 0.5) ** 2)
        bb_bbb_gap[i] += 200 * np.exp(-0.5 * ((y - 2020.2) / 0.2) ** 2)
        bb_bbb_gap[i] += 80 * np.exp(-0.5 * ((y - 2022.5) / 0.4) ** 2)
    bb_bbb_gap += np.random.normal(0, 10, N_HIST)
    bb_bbb_gap = np.clip(bb_bbb_gap, 60, 400)

    # --- HY Effective Yield (historical) ---
    us_hy_yield = np.zeros(N_HIST)
    eur_hy_yield = np.zeros(N_HIST)
    for i, y in enumerate(HIST_YEARS):
        us_hy_yield[i] = 5.5
        us_hy_yield[i] += 5.0 * np.exp(-0.5 * ((y - 2016) / 0.5) ** 2)
        us_hy_yield[i] += 8.0 * np.exp(-0.5 * ((y - 2020.2) / 0.2) ** 2)
        us_hy_yield[i] += 3.0 * np.exp(-0.5 * ((y - 2022.5) / 0.5) ** 2)
        us_hy_yield[i] -= 1.5 * np.exp(-0.5 * ((y - 2021) / 0.5) ** 2)
        eur_hy_yield[i] = us_hy_yield[i] * 0.85 + np.random.normal(0, 0.3)
    us_hy_yield += np.random.normal(0, 0.3, N_HIST)
    us_hy_yield = np.clip(us_hy_yield, 3, 15)
    eur_hy_yield = np.clip(eur_hy_yield, 2, 13)

    # Key metrics
    peak_year = YEARS[np.argmax(us_total)]
    two_yr_refi = us_total[0] + us_total[1] + eur_total[0] + eur_total[1]
    total_outstanding = sum(us_total) + sum(eur_total)
    supply_pressure = two_yr_refi / total_outstanding * 100
    latest_icr = icr[-1]
    fa_risk = "HIGH" if bb_bbb_gap[-1] > 200 else "MODERATE" if bb_bbb_gap[-1] > 150 else "LOW"

    return {
        "us_bb": us_bb, "us_b": us_b, "us_ccc": us_ccc,
        "eur_bb": eur_bb, "eur_b": eur_b, "eur_ccc": eur_ccc,
        "legacy_coupon": legacy_coupon, "current_refi": current_refi,
        "base_refi": base_refi, "rates_100": rates_100,
        "spreads_200": spreads_200, "crisis_500": crisis_500,
        "icr": icr, "bb_bbb_gap": bb_bbb_gap,
        "us_hy_yield": us_hy_yield, "eur_hy_yield": eur_hy_yield,
        "peak_year": peak_year, "two_yr_refi": two_yr_refi,
        "supply_pressure": supply_pressure, "latest_icr": latest_icr,
        "fa_risk": fa_risk,
    }


def generate_maturity_charts():
    """Generate HY maturity wall & refinancing charts — 2x4 layout."""
    setup_dark_style()
    data = _generate_maturity_data()

    fig = plt.figure(figsize=(26, 16), facecolor=COLORS["bg"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.suptitle("HIGH-YIELD MATURITY WALL & REFINANCING DASHBOARD",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {now} | US HY: 1450B | EUR HY: 450B",
             ha="center", fontsize=10, color=COLORS["text_dim"])

    gs = fig.add_gridspec(2, 4, hspace=0.4, wspace=0.35,
                          top=0.92, bottom=0.06, left=0.06, right=0.97)

    x = np.arange(N_YEARS)
    width = 0.6

    # =========================================================================
    # 1. US HY Maturity Wall by Rating (top-left)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 0])
    ax.bar(x, data["us_bb"], width, color=COLORS["cyan"], alpha=0.85, label="BB")
    ax.bar(x, data["us_b"], width, bottom=data["us_bb"],
           color=COLORS["orange"], alpha=0.85, label="B")
    ax.bar(x, data["us_ccc"], width,
           bottom=data["us_bb"] + data["us_b"],
           color=COLORS["red"], alpha=0.85, label="CCC")
    ax.set_xticks(x)
    ax.set_xticklabels(YEARS, rotation=45, fontsize=7)
    style_ax(ax, "US HY Maturity Wall by Rating ($B)", ylabel="$B")
    ax.legend(fontsize=7)

    # =========================================================================
    # 2. EUR HY Maturity Wall by Rating (top, second)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.bar(x, data["eur_bb"], width, color=COLORS["cyan"], alpha=0.85, label="BB")
    ax.bar(x, data["eur_b"], width, bottom=data["eur_bb"],
           color=COLORS["orange"], alpha=0.85, label="B")
    ax.bar(x, data["eur_ccc"], width,
           bottom=data["eur_bb"] + data["eur_b"],
           color=COLORS["red"], alpha=0.85, label="CCC")
    ax.set_xticks(x)
    ax.set_xticklabels(YEARS, rotation=45, fontsize=7)
    style_ax(ax, "EUR HY Maturity Wall by Rating ($B)", ylabel="$B")
    ax.legend(fontsize=7)

    # =========================================================================
    # 3. Legacy Coupon vs Current Refi Yield (top, third)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    w2 = 0.3
    ax.bar(x - w2 / 2, data["legacy_coupon"], w2, color=COLORS["green"],
           alpha=0.85, label="Legacy Coupon")
    ax.bar(x + w2 / 2, data["current_refi"], w2, color=COLORS["red"],
           alpha=0.85, label="Current Refi Yield")
    ax.set_xticks(x)
    ax.set_xticklabels(YEARS, rotation=45, fontsize=7)
    style_ax(ax, "Legacy Coupon vs Current Refi Yield", ylabel="Yield (%)")
    ax.legend(fontsize=7)

    # =========================================================================
    # 4. Avg Refi Yield Under Stress Scenarios (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 3])
    ax.plot(x, data["base_refi"], "o-", color=COLORS["cyan"],
            linewidth=1.5, markersize=3, label="Base")
    ax.plot(x, data["rates_100"], "s-", color=COLORS["orange"],
            linewidth=1.2, markersize=3, label="Rates +100bp")
    ax.plot(x, data["spreads_200"], "^-", color=COLORS["yellow"],
            linewidth=1.2, markersize=3, label="Spreads +200bp")
    ax.plot(x, data["crisis_500"], "D-", color=COLORS["red"],
            linewidth=1.2, markersize=3, label="HY Crisis +500bp")
    ax.set_xticks(x)
    ax.set_xticklabels(YEARS, rotation=45, fontsize=7)
    style_ax(ax, "Avg Refi Yield Under Stress Scenarios", ylabel="Yield (%)")
    ax.legend(fontsize=6)

    # =========================================================================
    # 5. Interest Coverage Ratio (bottom-left)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 0])
    hx = np.arange(N_HIST)
    ax.plot(hx, data["icr"], color=COLORS["cyan"], linewidth=1.5,
            marker="o", markersize=3)
    ax.fill_between(hx, data["icr"], alpha=0.15, color=COLORS["cyan"])
    ax.axhline(y=2.0, color=COLORS["red"], linestyle="--", linewidth=0.7,
               label="Stress (<2x)")
    ax.axhline(y=3.0, color=COLORS["yellow"], linestyle="--", linewidth=0.5,
               label="Watch (<3x)")
    ax.set_xticks(hx)
    ax.set_xticklabels(HIST_YEARS, rotation=45, fontsize=7)
    style_ax(ax, "Interest Coverage Ratio (Profits/Interest)", ylabel="ICR (x)")
    ax.legend(fontsize=7)

    # =========================================================================
    # 6. BB-BBB Spread Gap — Fallen Angel Indicator (bottom, second)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1])
    ax.plot(hx, data["bb_bbb_gap"], color=COLORS["purple"], linewidth=1.5,
            marker="o", markersize=3)
    ax.fill_between(hx, data["bb_bbb_gap"], alpha=0.15, color=COLORS["purple"])
    ax.axhline(y=200, color=COLORS["red"], linestyle="--", linewidth=0.7,
               label="High FA Risk (>200bp)")
    ax.axhline(y=150, color=COLORS["orange"], linestyle="--", linewidth=0.5,
               label="Moderate (>150bp)")
    ax.set_xticks(hx)
    ax.set_xticklabels(HIST_YEARS, rotation=45, fontsize=7)
    style_ax(ax, "BB-BBB Spread Gap (Fallen Angel Indicator)", ylabel="Spread (bps)")
    ax.legend(fontsize=6)

    # =========================================================================
    # 7. HY Effective Yield (bottom, third)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 2])
    ax.plot(hx, data["us_hy_yield"], color=COLORS["cyan"], linewidth=1.5,
            label="US HY")
    ax.plot(hx, data["eur_hy_yield"], color=COLORS["orange"], linewidth=1.5,
            label="EUR HY")
    ax.fill_between(hx, data["us_hy_yield"], alpha=0.1, color=COLORS["cyan"])
    ax.fill_between(hx, data["eur_hy_yield"], alpha=0.1, color=COLORS["orange"])
    ax.set_xticks(hx)
    ax.set_xticklabels(HIST_YEARS, rotation=45, fontsize=7)
    style_ax(ax, "HY Effective Yield (Refi Cost Proxy)", ylabel="Yield (%)")
    ax.legend(fontsize=7)

    # =========================================================================
    # 8. Key Metrics Box (bottom-right)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 3])
    ax.axis("off")

    icr_status = "HIGH STRESS" if data["latest_icr"] < 2.5 else \
                 "MODERATE" if data["latest_icr"] < 3.5 else "HEALTHY"
    icr_color = COLORS["red"] if data["latest_icr"] < 2.5 else \
                COLORS["orange"] if data["latest_icr"] < 3.5 else COLORS["green"]

    summary = (
        f"KEY METRICS\n"
        f"{'─' * 32}\n"
        f"Peak Wall:      {data['peak_year']}\n"
        f"2Y Refi Need:   ${data['two_yr_refi']:.0f}B\n"
        f"Supply Pressure: {data['supply_pressure']:.1f}%\n"
        f"{'─' * 32}\n"
        f"ICR: {data['latest_icr']:.1f}x ({icr_status})\n"
        f"FA Risk: {data['fa_risk']}\n"
        f"{'─' * 32}\n"
        f"HEAVY SUPPLY —\n"
        f"refi wall creates\n"
        f"headwind for spreads\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=COLORS["orange"], linewidth=2))
    style_ax(ax, "Key Metrics")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>HY Maturity Wall & Refinancing Dashboard</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Maturity Wall Charts">
</body></html>
"""


@maturity_bp.route("/maturity-wall")
def maturity_wall():
    chart = generate_maturity_charts()
    return render_template_string(TEMPLATE, chart=chart)
