"""
Portfolio Risk Manager
Route: /risk-manager

Greeks by position type, risk limits dashboard, JTD exposure,
VaR/CVaR, stress test P&L decomposition, notional breakdown,
margin utilization, and portfolio summary.
"""

import numpy as np
from datetime import datetime
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

risk_bp = Blueprint("risk_manager", __name__)

# ---------------------------------------------------------------------------
# Portfolio & risk data
# ---------------------------------------------------------------------------
AUM = 100_000_000  # $100mm
LEVERAGE = 4.0
GROSS_NOTIONAL = AUM * LEVERAGE  # $400mm


def _generate_risk_data():
    """Generate synthetic portfolio risk data."""
    np.random.seed(900)

    # Position types
    index_notional = GROSS_NOTIONAL * 0.93
    tranche_notional = GROSS_NOTIONAL * 0.07

    # Greeks by position type
    greeks = {
        "Index": {"CS01": 42_000, "Rho01": -18_000},
        "Tranche": {"CS01": -42_000, "Rho01": 18_000},
    }
    net_cs01 = sum(g["CS01"] for g in greeks.values())
    net_rho01 = sum(g["Rho01"] for g in greeks.values())

    # Risk limits
    limits = [
        {"name": "Max CS01", "current": abs(net_cs01) / AUM * 100,
         "limit": 0.5, "status": "OK"},
        {"name": "Max JTD Single Name", "current": 76,
         "limit": 100, "status": "OK"},
        {"name": "Max JTD Total", "current": 276,
         "limit": 100, "status": "BREACH"},
        {"name": "Max Leverage", "current": LEVERAGE / 10 * 100,
         "limit": 100, "status": "OK"},
        {"name": "Max VaR 99%", "current": 0.01,
         "limit": 5, "status": "OK"},
        {"name": "Max Rho01", "current": abs(net_rho01) / AUM * 100,
         "limit": 0.3, "status": "OK"},
    ]
    ok_count = sum(1 for l in limits if l["status"] == "OK")
    warn_count = sum(1 for l in limits if l["status"] == "WARN")
    breach_count = sum(1 for l in limits if l["status"] == "BREACH")

    # JTD top 10 names
    jtd_names = [f"Main_{i:03d}" for i in range(1, 11)]
    jtd_exposures = sorted(np.random.uniform(5, 35, 10), reverse=True)

    # VaR metrics
    var_metrics = {
        "VaR 95%": np.random.uniform(0.5, 1.5) * 1e6,
        "VaR 99%": np.random.uniform(1.0, 2.5) * 1e6,
        "CVaR 95%": np.random.uniform(1.5, 3.0) * 1e6,
        "CVaR 99%": np.random.uniform(2.5, 5.0) * 1e6,
    }

    # Stress test scenarios
    scenarios = ["Hard Landing", "Soft Landing", "No Landing",
                 "Stagflation", "Credit Crisis", "Correlation Spi",
                 "Multi Default", "Spread Gamma"]
    stress_pnl = {}
    for s in scenarios:
        spread = np.random.uniform(-5, 2) * 1e6
        corr = np.random.uniform(-2, 1) * 1e6
        default = np.random.uniform(-3, 0) * 1e6 if "Default" in s or "Crisis" in s else np.random.uniform(-0.5, 0.5) * 1e6
        net = spread + corr + default
        stress_pnl[s] = {"Spread": spread, "Correlation": corr,
                         "Default": default, "Net": net}

    # Margin
    initial_margin = AUM * 0.231
    available = AUM - initial_margin

    # Net theta
    net_theta = np.random.uniform(-500, 500)

    return {
        "greeks": greeks, "net_cs01": net_cs01, "net_rho01": net_rho01,
        "limits": limits, "ok_count": ok_count, "warn_count": warn_count,
        "breach_count": breach_count,
        "jtd_names": jtd_names, "jtd_exposures": jtd_exposures,
        "var_metrics": var_metrics, "stress_pnl": stress_pnl,
        "scenarios": scenarios,
        "index_notional": index_notional, "tranche_notional": tranche_notional,
        "initial_margin": initial_margin, "available": available,
        "net_theta": net_theta,
    }


def generate_risk_charts():
    """Generate portfolio risk manager charts — 3x3 layout."""
    setup_dark_style()
    data = _generate_risk_data()

    fig = plt.figure(figsize=(24, 18), facecolor=COLORS["bg"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.suptitle("PORTFOLIO RISK MANAGER",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {now} | AUM: $100mm | Leverage: {LEVERAGE:.1f}x",
             ha="center", fontsize=10, color=COLORS["text_dim"])

    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35,
                          top=0.92, bottom=0.04, left=0.07, right=0.97)

    # =========================================================================
    # 1. Greeks by Position Type (top-left)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 0])
    pos_types = list(data["greeks"].keys())
    x = np.arange(len(pos_types))
    width = 0.35
    cs01_vals = [data["greeks"][p]["CS01"] / 1000 for p in pos_types]
    rho01_vals = [data["greeks"][p]["Rho01"] / 1000 for p in pos_types]
    ax.bar(x - width / 2, cs01_vals, width, color=COLORS["cyan"],
           alpha=0.85, label="CS01 ($k)")
    ax.bar(x + width / 2, rho01_vals, width, color=COLORS["purple"],
           alpha=0.85, label="Rho01 ($k)")
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(pos_types, fontsize=9)
    for i, (c, r) in enumerate(zip(cs01_vals, rho01_vals)):
        ax.text(i - width / 2, c + (1 if c > 0 else -2), f"${c:.0f}k",
                ha="center", fontsize=7, color=COLORS["text"])
        ax.text(i + width / 2, r + (1 if r > 0 else -2), f"${r:.0f}k",
                ha="center", fontsize=7, color=COLORS["text"])
    style_ax(ax, "Greeks by Position Type", ylabel="$000s")
    ax.legend(fontsize=7)

    # =========================================================================
    # 2. Risk Limits Dashboard (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")

    limits = data["limits"]
    y_start = 0.92
    y_step = 0.13

    ax.text(0.5, 0.98, "RISK LIMITS", ha="center", va="top",
            fontsize=12, fontweight="bold", color=COLORS["text"],
            transform=ax.transAxes)

    for i, lim in enumerate(limits):
        y = y_start - i * y_step
        pct = min(lim["current"] / lim["limit"], 1.0) if lim["limit"] > 0 else 0

        status_color = COLORS["green"] if lim["status"] == "OK" else \
                       COLORS["orange"] if lim["status"] == "WARN" else COLORS["red"]
        status_label = f"[{'OK' if lim['status'] == 'OK' else 'XX'}]"

        ax.text(0.02, y, f"{status_label} {lim['name']}",
                fontsize=8, color=status_color, fontweight="bold",
                transform=ax.transAxes, va="center")
        ax.text(0.95, y, f"{lim['current']:.0f}%",
                fontsize=8, color=status_color, ha="right",
                transform=ax.transAxes, va="center")

        # Progress bar
        bar_left = 0.02
        bar_width = 0.91
        bar_y = y - 0.04
        bar_h = 0.025
        ax.add_patch(plt.Rectangle((bar_left, bar_y), bar_width, bar_h,
                                   transform=ax.transAxes,
                                   facecolor=COLORS["panel"], edgecolor=COLORS["grid"]))
        fill_color = status_color
        ax.add_patch(plt.Rectangle((bar_left, bar_y), bar_width * min(pct, 1.0), bar_h,
                                   transform=ax.transAxes,
                                   facecolor=fill_color, alpha=0.6))

    ax.text(0.5, 0.05,
            f"{data['ok_count']} OK | {data['warn_count']} WARN | {data['breach_count']} BREACH",
            ha="center", fontsize=9, fontweight="bold",
            color=COLORS["red"] if data["breach_count"] > 0 else COLORS["green"],
            transform=ax.transAxes)
    style_ax(ax, "")

    # =========================================================================
    # 3. JTD Exposure — Top 10 Names (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    jnames = data["jtd_names"]
    jvals = data["jtd_exposures"]
    colors = [COLORS["red"] if v > 25 else COLORS["orange"] if v > 15
              else COLORS["green"] for v in jvals]
    ax.barh(jnames, jvals, color=colors, alpha=0.85)
    for i, v in enumerate(jvals):
        ax.text(v + 0.3, i, f"${v:.1f}mm", va="center", fontsize=7,
                color=COLORS["text"])
    style_ax(ax, "JTD Exposure (Top 10 Names)", "$mm")
    ax.tick_params(axis="y", labelsize=7)

    # =========================================================================
    # 4. VaR (10-day) (mid-left)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 0])
    var_names = list(data["var_metrics"].keys())
    var_vals = [data["var_metrics"][k] / 1e6 for k in var_names]
    var_colors = [COLORS["cyan"], COLORS["orange"], COLORS["purple"], COLORS["red"]]
    bars = ax.bar(var_names, var_vals, color=var_colors, alpha=0.85)
    for bar, val in zip(bars, var_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.05,
                f"${val:.2f}mm", ha="center", fontsize=7, color=COLORS["text"])
    style_ax(ax, "VaR (10-day)", ylabel="$mm")

    # =========================================================================
    # 5. Stress Test P&L Decomposition (mid-center, wide)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1:])
    scenarios = data["scenarios"]
    x = np.arange(len(scenarios))
    width = 0.2
    components = ["Spread", "Correlation", "Default", "Net"]
    comp_colors = [COLORS["cyan"], COLORS["purple"], COLORS["red"], COLORS["yellow"]]

    for ci, (comp, color) in enumerate(zip(components, comp_colors)):
        vals = [data["stress_pnl"][s][comp] / 1e6 for s in scenarios]
        bars = ax.bar(x + ci * width, vals, width, color=color,
                      alpha=0.85, label=comp)

    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x + 1.5 * width)
    ax.set_xticklabels(scenarios, rotation=30, ha="right", fontsize=7)
    style_ax(ax, "Stress Test P&L Decomposition", ylabel="P&L ($mm)")
    ax.legend(fontsize=7, ncol=4)

    # =========================================================================
    # 6. Notional by Position Type (bottom-left, pie)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 0])
    sizes = [data["index_notional"], data["tranche_notional"]]
    labels = [f"Index\n{sizes[0]/1e6:.0f}mm ({sizes[0]/GROSS_NOTIONAL*100:.0f}%)",
              f"Tranche\n{sizes[1]/1e6:.0f}mm ({sizes[1]/GROSS_NOTIONAL*100:.0f}%)"]
    pie_colors = [COLORS["cyan"], COLORS["purple"]]
    wedges, texts = ax.pie(sizes, colors=pie_colors, startangle=90,
                           wedgeprops=dict(width=0.5, edgecolor=COLORS["bg"]))
    ax.legend(labels, fontsize=8, loc="center", framealpha=0.8,
              facecolor=COLORS["panel"], edgecolor=COLORS["grid"])
    style_ax(ax, "Notional by Position Type")

    # =========================================================================
    # 7. Margin Utilization (bottom-center)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 1])
    ax.axis("off")

    im_pct = data["initial_margin"] / AUM * 100
    av_pct = data["available"] / AUM * 100

    ax.text(0.5, 0.85, "MARGIN UTILIZATION", ha="center", fontsize=12,
            fontweight="bold", color=COLORS["text"], transform=ax.transAxes)

    # Available bar
    bar_y = 0.55
    bar_h = 0.12
    ax.add_patch(plt.Rectangle((0.05, bar_y), 0.9, bar_h,
                               transform=ax.transAxes,
                               facecolor=COLORS["panel"], edgecolor=COLORS["grid"]))
    ax.add_patch(plt.Rectangle((0.05, bar_y), 0.9 * (av_pct / 100), bar_h,
                               transform=ax.transAxes,
                               facecolor=COLORS["green"], alpha=0.6))
    ax.text(0.5, bar_y + bar_h / 2,
            f"Available ${data['available']/1e6:.1f}mm ({av_pct:.0f}%)",
            ha="center", va="center", fontsize=9, color=COLORS["text"],
            transform=ax.transAxes, fontweight="bold")

    # IM bar
    bar_y2 = 0.35
    ax.add_patch(plt.Rectangle((0.05, bar_y2), 0.9, bar_h,
                               transform=ax.transAxes,
                               facecolor=COLORS["panel"], edgecolor=COLORS["grid"]))
    ax.add_patch(plt.Rectangle((0.05, bar_y2), 0.9 * (im_pct / 100), bar_h,
                               transform=ax.transAxes,
                               facecolor=COLORS["orange"], alpha=0.6))
    ax.text(0.5, bar_y2 + bar_h / 2,
            f"Initial Margin ${data['initial_margin']/1e6:.1f}mm ({im_pct:.0f}%)",
            ha="center", va="center", fontsize=9, color=COLORS["text"],
            transform=ax.transAxes, fontweight="bold")

    style_ax(ax, "")

    # =========================================================================
    # 8. Portfolio Summary Box (bottom-right)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 2])
    ax.axis("off")

    var99_pct = data["var_metrics"]["VaR 99%"] / AUM * 100
    summary = (
        f"PORTFOLIO SUMMARY\n"
        f"{'─' * 34}\n"
        f"AUM:              $100mm\n"
        f"Gross Notional:   ${GROSS_NOTIONAL/1e6:.0f}mm\n"
        f"Leverage:         {LEVERAGE:.1f}x\n"
        f"{'─' * 34}\n"
        f"Net CS01:         ${data['net_cs01']:+,.0f}\n"
        f"Net Rho01:        ${data['net_rho01']:+,.0f}\n"
        f"Net Theta/day:    ${data['net_theta']:+,.0f}\n"
        f"{'─' * 34}\n"
        f"VaR 99% (10d):    ${data['var_metrics']['VaR 99%']/1e6:.1f}mm ({var99_pct:.2f}%)\n"
        f"Est. IM:          ${data['initial_margin']/1e6:.1f}mm ({data['initial_margin']/AUM*100:.0f}%)\n"
        f"Positions:        5\n"
        f"Limits:           {data['ok_count']}OK/{data['warn_count']}WARN/{data['breach_count']}BREACH\n"
    )

    border = COLORS["red"] if data["breach_count"] > 0 else COLORS["green"]
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=9,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=border, linewidth=2))
    style_ax(ax, "Portfolio Summary")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Portfolio Risk Manager</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Risk Manager Charts">
</body></html>
"""


@risk_bp.route("/risk-manager")
def risk_manager():
    chart = generate_risk_charts()
    return render_template_string(TEMPLATE, chart=chart)
