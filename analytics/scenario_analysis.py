"""
Scenario Analysis Engine
Route: /scenario-analysis

Macro scenario P&L attribution, portfolio returns by scenario, P&L decomposition,
hedge effectiveness, spread impact by rating, scenario probability summary.
"""

import numpy as np
from datetime import datetime
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

scenario_bp = Blueprint("scenario_analysis", __name__)

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------
SCENARIOS = [
    "Hard Landing", "Soft Landing", "No Landing", "Stagflation",
    "Credit Crisis", "Rate Spike", "ECB Easing", "Geopolitical",
]

RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]


def _generate_scenario_data():
    """Generate synthetic scenario analysis data."""
    np.random.seed(910)

    n = len(SCENARIOS)

    # --- Scenario probabilities ---
    raw_probs = np.array([0.12, 0.30, 0.25, 0.10, 0.05, 0.08, 0.07, 0.03])
    probs = raw_probs / raw_probs.sum() * 100  # %

    # --- Portfolio returns by scenario (%) ---
    returns = np.array([
        -8.5,   # Hard Landing
         3.2,   # Soft Landing
         5.1,   # No Landing
        -4.2,   # Stagflation
       -15.0,   # Credit Crisis
        -2.5,   # Rate Spike
         4.8,   # ECB Easing
        -6.0,   # Geopolitical
    ]) + np.random.normal(0, 0.5, n)

    # --- P&L decomposition by component ---
    components = ["Carry", "Spread MTM", "Rate MTM", "Default", "Basis", "Fees"]
    pnl_decomp = {}
    for i, sc in enumerate(SCENARIOS):
        carry = np.random.uniform(0.5, 2.0)
        spread = returns[i] * 0.6 + np.random.normal(0, 0.5)
        rate = -returns[i] * 0.15 + np.random.normal(0, 0.3)
        default = -abs(returns[i]) * 0.1 if returns[i] < -5 else np.random.uniform(-0.3, 0)
        basis = np.random.normal(0, 0.3)
        fees = -np.random.uniform(0.1, 0.4)
        pnl_decomp[sc] = {
            "Carry": carry, "Spread MTM": spread, "Rate MTM": rate,
            "Default": default, "Basis": basis, "Fees": fees,
        }

    # --- Hedge effectiveness ---
    hedge_instruments = ["CDS Index Short", "Rate Swap", "Put Options",
                         "FX Hedge", "Vol Overlay"]
    hedge_data = {}
    for sc in SCENARIOS:
        h = {}
        for inst in hedge_instruments:
            if "Crisis" in sc or "Hard" in sc or "Geo" in sc:
                h[inst] = np.random.uniform(0.5, 4.0)
            elif "Landing" in sc and "Soft" in sc:
                h[inst] = np.random.uniform(-1.0, 0.5)
            else:
                h[inst] = np.random.uniform(-0.5, 1.5)
        hedge_data[sc] = h

    # --- Spread impact by rating ---
    spread_impact = {}
    for sc in SCENARIOS:
        impacts = {}
        for j, r in enumerate(RATINGS):
            base = returns[SCENARIOS.index(sc)] * (-10) * (j + 1) / 4
            impacts[r] = base + np.random.normal(0, 5)
        spread_impact[sc] = impacts

    # --- Expected return (probability-weighted) ---
    expected_return = sum(p / 100 * r for p, r in zip(probs, returns))

    # --- Worst-case / best-case ---
    worst_sc = SCENARIOS[np.argmin(returns)]
    best_sc = SCENARIOS[np.argmax(returns)]

    return {
        "probs": probs, "returns": returns, "pnl_decomp": pnl_decomp,
        "components": components, "hedge_data": hedge_data,
        "hedge_instruments": hedge_instruments,
        "spread_impact": spread_impact,
        "expected_return": expected_return,
        "worst_sc": worst_sc, "best_sc": best_sc,
    }


def generate_scenario_charts():
    """Generate scenario analysis charts — 3x3 layout."""
    setup_dark_style()
    data = _generate_scenario_data()

    fig = plt.figure(figsize=(26, 18), facecolor=COLORS["bg"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.suptitle("SCENARIO ANALYSIS ENGINE",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {now} | {len(SCENARIOS)} scenarios | "
             f"E[Return]: {data['expected_return']:+.2f}%",
             ha="center", fontsize=10, color=COLORS["text_dim"])

    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35,
                          top=0.92, bottom=0.04, left=0.07, right=0.97)

    n = len(SCENARIOS)
    x = np.arange(n)

    # =========================================================================
    # 1. Portfolio Returns by Scenario (top-left)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 0])
    ret = data["returns"]
    bar_colors = [COLORS["green"] if r > 0 else COLORS["red"] for r in ret]
    bars = ax.bar(x, ret, color=bar_colors, alpha=0.85, width=0.6)
    for bar, val in zip(bars, ret):
        offset = 0.3 if val > 0 else -0.5
        ax.text(bar.get_x() + bar.get_width() / 2, val + offset,
                f"{val:+.1f}%", ha="center", fontsize=6.5, color=COLORS["text"])
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.axhline(y=data["expected_return"], color=COLORS["yellow"],
               linewidth=1, linestyle="--",
               label=f"E[R] = {data['expected_return']:+.2f}%")
    ax.set_xticks(x)
    ax.set_xticklabels(SCENARIOS, rotation=35, ha="right", fontsize=6.5)
    style_ax(ax, "Portfolio Returns by Scenario", ylabel="Return (%)")
    ax.legend(fontsize=7)

    # =========================================================================
    # 2. Scenario Probabilities (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    probs = data["probs"]
    sorted_idx = np.argsort(probs)[::-1]
    sorted_sc = [SCENARIOS[i] for i in sorted_idx]
    sorted_probs = probs[sorted_idx]
    prob_colors = [PALETTE[i % len(PALETTE)] for i in range(n)]
    ax.barh(sorted_sc, sorted_probs, color=prob_colors, alpha=0.85)
    for i, v in enumerate(sorted_probs):
        ax.text(v + 0.3, i, f"{v:.1f}%", va="center", fontsize=7,
                color=COLORS["text"])
    ax.axvline(x=100 / n, color=COLORS["text_dim"], linewidth=0.7,
               linestyle="--", label=f"Uniform ({100/n:.1f}%)")
    style_ax(ax, "Scenario Probabilities", "Probability (%)")
    ax.legend(fontsize=7)

    # =========================================================================
    # 3. Summary Box (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    ax.axis("off")

    ret_arr = data["returns"]
    p_arr = data["probs"]
    e_ret = data["expected_return"]
    vol = np.sqrt(np.sum(p_arr / 100 * (ret_arr - e_ret) ** 2))
    sharpe_proxy = e_ret / vol if vol > 0 else 0

    summary = (
        f"SCENARIO SUMMARY\n"
        f"{'─' * 34}\n"
        f"Scenarios:      {n}\n"
        f"E[Return]:      {e_ret:+.2f}%\n"
        f"Scenario Vol:   {vol:.2f}%\n"
        f"Sharpe (proxy): {sharpe_proxy:.2f}\n"
        f"{'─' * 34}\n"
        f"Best Case:      {data['best_sc']}\n"
        f"  Return:       {ret_arr.max():+.1f}%\n"
        f"Worst Case:     {data['worst_sc']}\n"
        f"  Return:       {ret_arr.min():+.1f}%\n"
        f"{'─' * 34}\n"
        f"Base Case:      Soft Landing\n"
        f"  Probability:  {probs[1]:.0f}%\n"
    )
    border = COLORS["green"] if e_ret > 0 else COLORS["red"]
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=9,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=border, linewidth=2))
    style_ax(ax, "Scenario Summary")

    # =========================================================================
    # 4. P&L Decomposition by Scenario (mid, full width)
    # =========================================================================
    ax = fig.add_subplot(gs[1, :])
    components = data["components"]
    comp_colors = [COLORS["green"], COLORS["cyan"], COLORS["purple"],
                   COLORS["red"], COLORS["yellow"], COLORS["text_dim"]]
    width = 0.12
    for ci, (comp, cc) in enumerate(zip(components, comp_colors)):
        vals = [data["pnl_decomp"][sc][comp] for sc in SCENARIOS]
        ax.bar(x + ci * width, vals, width, color=cc, alpha=0.85, label=comp)

    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x + width * 2.5)
    ax.set_xticklabels(SCENARIOS, rotation=25, ha="right", fontsize=7)
    style_ax(ax, "P&L Decomposition by Scenario", ylabel="P&L (%)")
    ax.legend(fontsize=7, ncol=6, loc="upper right")

    # =========================================================================
    # 5. Hedge Effectiveness (bottom-left + center)
    # =========================================================================
    ax = fig.add_subplot(gs[2, :2])
    instruments = data["hedge_instruments"]
    width_h = 0.15
    for hi, inst in enumerate(instruments):
        vals = [data["hedge_data"][sc][inst] for sc in SCENARIOS]
        ax.bar(x + hi * width_h, vals, width_h, alpha=0.85,
               color=PALETTE[hi % len(PALETTE)], label=inst)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x + width_h * 2)
    ax.set_xticklabels(SCENARIOS, rotation=25, ha="right", fontsize=7)
    style_ax(ax, "Hedge P&L by Scenario & Instrument", ylabel="Hedge P&L (%)")
    ax.legend(fontsize=6, ncol=3)

    # =========================================================================
    # 6. Spread Impact by Rating (bottom-right)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 2])
    # Heatmap: scenarios x ratings
    import matplotlib.colors as mcolors
    heat = np.zeros((n, len(RATINGS)))
    for i, sc in enumerate(SCENARIOS):
        for j, r in enumerate(RATINGS):
            heat[i, j] = data["spread_impact"][sc][r]

    vmax = np.abs(heat).max()
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "spread", [COLORS["green"], COLORS["bg"], COLORS["red"]])
    im = ax.imshow(heat, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(RATINGS)))
    ax.set_yticks(range(n))
    ax.set_xticklabels(RATINGS, fontsize=7)
    ax.set_yticklabels(SCENARIOS, fontsize=6.5)
    for i in range(n):
        for j in range(len(RATINGS)):
            ax.text(j, i, f"{heat[i,j]:+.0f}", ha="center", va="center",
                    fontsize=5.5, color=COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.7, label="Spread Δ (bps)")
    style_ax(ax, "Spread Impact by Rating (bps)")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Scenario Analysis Engine</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Scenario Analysis Charts">
</body></html>
"""


@scenario_bp.route("/scenario-analysis")
def scenario_analysis():
    chart = generate_scenario_charts()
    return render_template_string(TEMPLATE, chart=chart)
