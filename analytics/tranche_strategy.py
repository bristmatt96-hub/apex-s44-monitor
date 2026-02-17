"""
Tranche Strategy Engine
Route: /tranche-strategy

P&L waterfall, signal dashboard, delta hedge ratios, stress scenarios,
carry/roll-down analysis, P&L sensitivity heatmap, and position summary.
"""

import numpy as np
from datetime import datetime
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

tranche_bp = Blueprint("tranche_strategy", __name__)

# ---------------------------------------------------------------------------
# Tranche data
# ---------------------------------------------------------------------------
TRANCHES = ["0-3%", "3-6%", "6-9%", "9-12%", "12-22%"]
INDICES = ["iTraxx Main", "iTraxx Xover"]


def _generate_tranche_data():
    """Generate synthetic tranche strategy data."""
    np.random.seed(920)

    # --- P&L Waterfall ---
    waterfall_items = [
        "Opening P&L", "Carry", "Spread MTM", "Correlation MTM",
        "Roll-Down", "Delta Hedge", "Gamma", "Theta Decay",
        "Basis", "Fees", "Closing P&L",
    ]
    wf_vals = [0.0]  # Opening = 0
    wf_vals.append(np.random.uniform(150, 300))        # Carry
    wf_vals.append(np.random.uniform(-200, 400))        # Spread MTM
    wf_vals.append(np.random.uniform(-300, 200))        # Correlation MTM
    wf_vals.append(np.random.uniform(30, 100))          # Roll-down
    wf_vals.append(np.random.uniform(-150, 50))         # Delta hedge
    wf_vals.append(np.random.uniform(-80, 80))          # Gamma
    wf_vals.append(np.random.uniform(-100, -20))        # Theta decay
    wf_vals.append(np.random.uniform(-40, 40))          # Basis
    wf_vals.append(np.random.uniform(-50, -10))         # Fees
    wf_vals.append(sum(wf_vals[1:]))                    # Closing = sum of all

    # --- Signal Dashboard ---
    signals = {
        "Spread Direction": {"value": np.random.choice([-1, 0, 1]),
                             "strength": np.random.uniform(0.3, 1.0)},
        "Correlation": {"value": np.random.choice([-1, 0, 1]),
                        "strength": np.random.uniform(0.3, 1.0)},
        "Skew": {"value": np.random.choice([-1, 0, 1]),
                 "strength": np.random.uniform(0.2, 0.9)},
        "Carry Attractiveness": {"value": 1, "strength": np.random.uniform(0.5, 1.0)},
        "Vol Regime": {"value": np.random.choice([-1, 0, 1]),
                       "strength": np.random.uniform(0.4, 1.0)},
        "Macro Composite": {"value": np.random.choice([-1, 0, 1]),
                            "strength": np.random.uniform(0.3, 0.8)},
    }

    # --- Delta Hedge Ratios by Tranche ---
    delta_ratios = {}
    for tr in TRANCHES:
        for idx in INDICES:
            delta_ratios[(tr, idx)] = np.random.uniform(0.5, 15.0)

    # --- Stress Scenarios P&L ($k) ---
    stress_scenarios = ["Spreads +50bp", "Spreads -50bp",
                        "Corr +10%", "Corr -10%",
                        "Default 1 Name", "Default 3 Names",
                        "Rates +100bp", "Vol Spike"]
    stress_pnl = {}
    for sc in stress_scenarios:
        vals = {}
        for tr in TRANCHES:
            if "Default" in sc:
                # Equity tranche hit hardest
                idx = TRANCHES.index(tr)
                vals[tr] = np.random.uniform(-500, -10) * (5 - idx) / 5
            elif "+50bp" in sc:
                idx = TRANCHES.index(tr)
                vals[tr] = np.random.uniform(-300, 100) * (5 - idx) / 4
            elif "-50bp" in sc:
                idx = TRANCHES.index(tr)
                vals[tr] = np.random.uniform(-50, 300) * (5 - idx) / 4
            elif "Corr" in sc:
                vals[tr] = np.random.uniform(-200, 200)
            else:
                vals[tr] = np.random.uniform(-150, 150)
        stress_pnl[sc] = vals

    # --- Carry & Roll-Down Analysis (monthly, 12m) ---
    months = [f"M{i}" for i in range(1, 13)]
    carry_data = {}
    for tr in TRANCHES:
        monthly_carry = np.random.uniform(10, 60, 12)
        # Taper for senior tranches
        idx = TRANCHES.index(tr)
        monthly_carry *= (5 - idx) / 3
        carry_data[tr] = np.cumsum(monthly_carry)

    # --- P&L Sensitivity Heatmap (spread shift x correlation shift) ---
    spread_shifts = [-100, -75, -50, -25, 0, 25, 50, 75, 100]
    corr_shifts = [-20, -15, -10, -5, 0, 5, 10, 15, 20]
    sens_heat = np.zeros((len(corr_shifts), len(spread_shifts)))
    for i, cs in enumerate(corr_shifts):
        for j, ss in enumerate(spread_shifts):
            sens_heat[i, j] = -ss * 3.5 + cs * 8.0 + np.random.normal(0, 30)

    # --- Position Summary ---
    total_notional = 50_000_000  # $50mm
    net_cs01 = np.random.uniform(-5000, 5000)
    net_corr01 = np.random.uniform(-8000, 8000)
    net_carry_day = np.random.uniform(500, 2000)
    net_theta = np.random.uniform(-300, -50)

    return {
        "waterfall_items": waterfall_items, "wf_vals": wf_vals,
        "signals": signals,
        "delta_ratios": delta_ratios,
        "stress_scenarios": stress_scenarios, "stress_pnl": stress_pnl,
        "months": months, "carry_data": carry_data,
        "spread_shifts": spread_shifts, "corr_shifts": corr_shifts,
        "sens_heat": sens_heat,
        "total_notional": total_notional, "net_cs01": net_cs01,
        "net_corr01": net_corr01, "net_carry_day": net_carry_day,
        "net_theta": net_theta,
    }


def generate_tranche_charts():
    """Generate tranche strategy charts — 3x3 layout."""
    setup_dark_style()
    data = _generate_tranche_data()

    fig = plt.figure(figsize=(26, 18), facecolor=COLORS["bg"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.suptitle("TRANCHE STRATEGY ENGINE",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {now} | Tranches: {', '.join(TRANCHES)} | "
             f"Notional: ${data['total_notional']/1e6:.0f}mm",
             ha="center", fontsize=10, color=COLORS["text_dim"])

    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35,
                          top=0.92, bottom=0.04, left=0.07, right=0.97)

    # =========================================================================
    # 1. P&L Waterfall (top-left + center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, :2])
    items = data["waterfall_items"]
    vals = data["wf_vals"]
    n_items = len(items)

    # Build waterfall: running total for bottom
    bottoms = [0] * n_items
    display_vals = list(vals)
    running = 0
    for i in range(1, n_items - 1):  # skip opening and closing
        bottoms[i] = running
        running += vals[i]
    bottoms[-1] = 0  # Closing starts from 0

    bar_colors = []
    for i, v in enumerate(display_vals):
        if i == 0:
            bar_colors.append(COLORS["text_dim"])
        elif i == n_items - 1:
            bar_colors.append(COLORS["cyan"] if v > 0 else COLORS["red"])
        elif v > 0:
            bar_colors.append(COLORS["green"])
        else:
            bar_colors.append(COLORS["red"])

    x_wf = np.arange(n_items)
    bars = ax.bar(x_wf, display_vals, color=bar_colors, alpha=0.85,
                  bottom=bottoms, width=0.6)
    for i, (bar, val) in enumerate(zip(bars, display_vals)):
        y_pos = bottoms[i] + val + (15 if val > 0 else -25)
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                f"${val:+,.0f}k" if abs(val) > 1 else "$0",
                ha="center", fontsize=6, color=COLORS["text"])

    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x_wf)
    ax.set_xticklabels(items, rotation=35, ha="right", fontsize=7)
    style_ax(ax, "P&L Waterfall ($k)", ylabel="P&L ($k)")

    # =========================================================================
    # 2. Signal Dashboard (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    ax.axis("off")

    signals = data["signals"]
    y_start = 0.9
    y_step = 0.13

    ax.text(0.5, 0.97, "SIGNAL DASHBOARD", ha="center", va="top",
            fontsize=12, fontweight="bold", color=COLORS["text"],
            transform=ax.transAxes)

    for i, (name, sig) in enumerate(signals.items()):
        y = y_start - i * y_step
        val = sig["value"]
        strength = sig["strength"]

        if val > 0:
            signal_text = "BULLISH"
            sig_color = COLORS["green"]
        elif val < 0:
            signal_text = "BEARISH"
            sig_color = COLORS["red"]
        else:
            signal_text = "NEUTRAL"
            sig_color = COLORS["yellow"]

        ax.text(0.02, y, name, fontsize=8, color=COLORS["text"],
                transform=ax.transAxes, va="center")
        ax.text(0.65, y, signal_text, fontsize=8, color=sig_color,
                fontweight="bold", transform=ax.transAxes, va="center")

        # Strength bar
        bar_y = y - 0.04
        bar_h = 0.02
        ax.add_patch(plt.Rectangle((0.02, bar_y), 0.55, bar_h,
                                   transform=ax.transAxes,
                                   facecolor=COLORS["panel"],
                                   edgecolor=COLORS["grid"]))
        ax.add_patch(plt.Rectangle((0.02, bar_y), 0.55 * strength, bar_h,
                                   transform=ax.transAxes,
                                   facecolor=sig_color, alpha=0.5))
        ax.text(0.59, bar_y + bar_h / 2, f"{strength:.0%}",
                fontsize=6, color=COLORS["text_dim"],
                transform=ax.transAxes, va="center")
    style_ax(ax, "")

    # =========================================================================
    # 3. Delta Hedge Ratios (mid-left)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 0])
    x_tr = np.arange(len(TRANCHES))
    width = 0.35
    main_vals = [data["delta_ratios"][(tr, "iTraxx Main")] for tr in TRANCHES]
    xover_vals = [data["delta_ratios"][(tr, "iTraxx Xover")] for tr in TRANCHES]
    ax.bar(x_tr - width / 2, main_vals, width, color=COLORS["cyan"],
           alpha=0.85, label="iTraxx Main")
    ax.bar(x_tr + width / 2, xover_vals, width, color=COLORS["orange"],
           alpha=0.85, label="iTraxx Xover")
    for i in range(len(TRANCHES)):
        ax.text(i - width / 2, main_vals[i] + 0.2, f"{main_vals[i]:.1f}",
                ha="center", fontsize=6, color=COLORS["text"])
        ax.text(i + width / 2, xover_vals[i] + 0.2, f"{xover_vals[i]:.1f}",
                ha="center", fontsize=6, color=COLORS["text"])
    ax.set_xticks(x_tr)
    ax.set_xticklabels(TRANCHES, fontsize=8)
    style_ax(ax, "Delta Hedge Ratios by Tranche", ylabel="Delta Ratio")
    ax.legend(fontsize=7)

    # =========================================================================
    # 4. Stress Scenario P&L by Tranche (mid-center + right)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1:])
    scenarios = data["stress_scenarios"]
    x_sc = np.arange(len(scenarios))
    w = 0.15
    tr_colors = [COLORS["red"], COLORS["orange"], COLORS["yellow"],
                 COLORS["cyan"], COLORS["green"]]
    for ti, tr in enumerate(TRANCHES):
        vals = [data["stress_pnl"][sc][tr] for sc in scenarios]
        ax.bar(x_sc + ti * w, vals, w, color=tr_colors[ti],
               alpha=0.85, label=tr)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x_sc + w * 2)
    ax.set_xticklabels(scenarios, rotation=30, ha="right", fontsize=6.5)
    style_ax(ax, "Stress Scenario P&L by Tranche ($k)", ylabel="P&L ($k)")
    ax.legend(fontsize=6, ncol=5)

    # =========================================================================
    # 5. Carry & Roll-Down (cumulative, bottom-left)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 0])
    months = data["months"]
    x_m = np.arange(len(months))
    for ti, tr in enumerate(TRANCHES):
        ax.plot(x_m, data["carry_data"][tr], "o-", color=tr_colors[ti],
                linewidth=1.2, markersize=3, label=tr)
    ax.set_xticks(x_m)
    ax.set_xticklabels(months, fontsize=7, rotation=30)
    style_ax(ax, "Cumulative Carry + Roll-Down ($k)", ylabel="$k")
    ax.legend(fontsize=6, ncol=2)

    # =========================================================================
    # 6. P&L Sensitivity Heatmap (bottom-center)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 1])
    heat = data["sens_heat"]
    vmax = np.abs(heat).max()
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "pnl_sens", [COLORS["red"], COLORS["bg"], COLORS["green"]])
    im = ax.imshow(heat, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(data["spread_shifts"])))
    ax.set_yticks(range(len(data["corr_shifts"])))
    ax.set_xticklabels([f"{s:+d}" for s in data["spread_shifts"]],
                       fontsize=6, rotation=30)
    ax.set_yticklabels([f"{c:+d}%" for c in data["corr_shifts"]], fontsize=6)
    ax.set_xlabel("Spread Shift (bps)", fontsize=7, color=COLORS["text"])
    ax.set_ylabel("Corr Shift (%)", fontsize=7, color=COLORS["text"])
    for i in range(len(data["corr_shifts"])):
        for j in range(len(data["spread_shifts"])):
            ax.text(j, i, f"{heat[i,j]:+.0f}", ha="center", va="center",
                    fontsize=4.5, color=COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.7, label="P&L ($k)")
    style_ax(ax, "P&L Sensitivity (Spread x Correlation)")

    # =========================================================================
    # 7. Position Summary (bottom-right)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 2])
    ax.axis("off")

    closing = data["wf_vals"][-1]
    summary = (
        f"POSITION SUMMARY\n"
        f"{'─' * 32}\n"
        f"Notional:       ${data['total_notional']/1e6:.0f}mm\n"
        f"Tranches:       {len(TRANCHES)}\n"
        f"{'─' * 32}\n"
        f"Net CS01:       ${data['net_cs01']:+,.0f}\n"
        f"Net Corr01:     ${data['net_corr01']:+,.0f}\n"
        f"Carry/day:      ${data['net_carry_day']:+,.0f}\n"
        f"Theta/day:      ${data['net_theta']:+,.0f}\n"
        f"{'─' * 32}\n"
        f"Session P&L:    ${closing:+,.0f}k\n"
        f"Signals:        Mixed\n"
    )
    border = COLORS["green"] if closing > 0 else COLORS["red"]
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=9.5,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=border, linewidth=2))
    style_ax(ax, "Position Summary")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Tranche Strategy Engine</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Tranche Strategy Charts">
</body></html>
"""


@tranche_bp.route("/tranche-strategy")
def tranche_strategy():
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("tranche-strategy", generate_tranche_charts)
    return render_template_string(TEMPLATE, chart=chart)
