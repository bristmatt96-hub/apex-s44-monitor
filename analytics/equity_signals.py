"""
Equity-Implied Credit Signals — iTraxx Crossover Constituents
Route: /equity-signals

Composite credit signal from Vol (25%), Momentum (25%), Drawdown (20%),
Leverage (20%), Beta (10%). Per-name signal classifications, sector heatmap,
signal vs drawdown scatter, and top 10 bearish names breakdown.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

equity_signals_bp = Blueprint("equity_signals", __name__)

# ---------------------------------------------------------------------------
# iTraxx Crossover constituents (~43 names)
# ---------------------------------------------------------------------------
WEIGHTS = {"Vol": 0.25, "Momentum": 0.25, "Drawdown": 0.20,
           "Leverage": 0.20, "Beta": 0.10}

SECTORS = [
    "Autos", "Banks", "Basic Resources", "Chemicals", "Construction",
    "Consumer Goods", "Energy", "Financial Services", "Food & Beverage",
    "Healthcare", "Industrials", "Insurance", "Media", "Real Estate",
    "Retail", "Technology", "Telecom", "Travel & Leisure", "Utilities"
]

CONSTITUENTS = [
    {"name": "Ardagh Packaging", "sector": "Basic Resources"},
    {"name": "Casino Guichard", "sector": "Retail"},
    {"name": "Altice France", "sector": "Telecom"},
    {"name": "Intrum", "sector": "Financial Services"},
    {"name": "Atos", "sector": "Technology"},
    {"name": "SFR", "sector": "Telecom"},
    {"name": "Teva Pharma", "sector": "Healthcare"},
    {"name": "Grifols", "sector": "Healthcare"},
    {"name": "Telecom Italia", "sector": "Telecom"},
    {"name": "Bayer", "sector": "Chemicals"},
    {"name": "Loxam", "sector": "Industrials"},
    {"name": "Stonegate", "sector": "Travel & Leisure"},
    {"name": "Verisure", "sector": "Industrials"},
    {"name": "Picard", "sector": "Food & Beverage"},
    {"name": "Maxeda", "sector": "Retail"},
    {"name": "Renault", "sector": "Autos"},
    {"name": "Peugeot", "sector": "Autos"},
    {"name": "Vodafone", "sector": "Telecom"},
    {"name": "Nokia", "sector": "Technology"},
    {"name": "Lufthansa", "sector": "Travel & Leisure"},
    {"name": "Rolls-Royce", "sector": "Industrials"},
    {"name": "ThyssenKrupp", "sector": "Basic Resources"},
    {"name": "ArcelorMittal", "sector": "Basic Resources"},
    {"name": "Heidelberg Cement", "sector": "Construction"},
    {"name": "Repsol", "sector": "Energy"},
    {"name": "EDP", "sector": "Utilities"},
    {"name": "Enel", "sector": "Utilities"},
    {"name": "Unibail", "sector": "Real Estate"},
    {"name": "ING Group", "sector": "Banks"},
    {"name": "Commerzbank", "sector": "Banks"},
    {"name": "Aegon", "sector": "Insurance"},
    {"name": "Adecco", "sector": "Industrials"},
    {"name": "Marks & Spencer", "sector": "Retail"},
    {"name": "Carrefour", "sector": "Retail"},
    {"name": "Vivendi", "sector": "Media"},
    {"name": "ProSiebenSat.1", "sector": "Media"},
    {"name": "TUI", "sector": "Travel & Leisure"},
    {"name": "IAG", "sector": "Travel & Leisure"},
    {"name": "Leonardo", "sector": "Industrials"},
    {"name": "Continental", "sector": "Autos"},
    {"name": "Pernod Ricard", "sector": "Food & Beverage"},
    {"name": "Danone", "sector": "Food & Beverage"},
    {"name": "Accor", "sector": "Travel & Leisure"},
]


def _generate_equity_signal_data():
    """Generate synthetic equity-implied credit signals."""
    np.random.seed(555)

    names_data = []
    for c in CONSTITUENTS:
        # Component z-scores (negative = bearish for credit)
        vol_z = np.random.normal(-0.3, 1.0)
        mom_z = np.random.normal(-0.2, 1.0)
        dd_z = np.random.normal(-0.4, 0.9)
        lev_z = np.random.normal(-0.3, 0.8)
        beta_z = np.random.normal(-0.1, 0.7)

        composite = (WEIGHTS["Vol"] * vol_z +
                     WEIGHTS["Momentum"] * mom_z +
                     WEIGHTS["Drawdown"] * dd_z +
                     WEIGHTS["Leverage"] * lev_z +
                     WEIGHTS["Beta"] * beta_z)

        # Classification
        if composite < -1.0:
            signal = "STRONG D"
        elif composite < -0.3:
            signal = "DETERIORATING"
        elif composite < 0.3:
            signal = "NEUTRAL"
        elif composite < 1.0:
            signal = "IMPROVING"
        else:
            signal = "STRONG IMPROV"

        # Drawdown for scatter
        drawdown = np.random.uniform(-35, -2)

        names_data.append({
            "name": c["name"], "sector": c["sector"],
            "vol": vol_z, "momentum": mom_z, "drawdown_z": dd_z,
            "leverage": lev_z, "beta": beta_z, "composite": composite,
            "signal": signal, "dd_pct": drawdown,
        })

    # Sort by composite
    names_data.sort(key=lambda x: x["composite"])

    # Sector aggregation
    sector_signals = {}
    for s in SECTORS:
        sector_names = [n for n in names_data if n["sector"] == s]
        if sector_names:
            sector_signals[s] = {
                "Vol": np.mean([n["vol"] for n in sector_names]),
                "Momentum": np.mean([n["momentum"] for n in sector_names]),
                "Drawdown": np.mean([n["drawdown_z"] for n in sector_names]),
                "Leverage": np.mean([n["leverage"] for n in sector_names]),
                "Beta": np.mean([n["beta"] for n in sector_names]),
                "Composite": np.mean([n["composite"] for n in sector_names]),
            }

    # Summary stats
    composites = [n["composite"] for n in names_data]
    strong_d = sum(1 for n in names_data if n["signal"] == "STRONG D")
    deter = sum(1 for n in names_data if n["signal"] == "DETERIORATING")
    neutral = sum(1 for n in names_data if n["signal"] == "NEUTRAL")
    improving = sum(1 for n in names_data if n["signal"] == "IMPROVING")
    strong_imp = sum(1 for n in names_data if n["signal"] == "STRONG IMPROV")

    return {
        "names_data": names_data,
        "sector_signals": sector_signals,
        "avg_composite": np.mean(composites),
        "strong_d": strong_d, "deteriorating": deter,
        "neutral": neutral, "improving": improving,
        "strong_improv": strong_imp,
    }


def generate_equity_signal_charts():
    """Generate equity-implied credit signal charts — 2x3 layout."""
    setup_dark_style()
    data = _generate_equity_signal_data()

    fig = plt.figure(figsize=(26, 18), facecolor=COLORS["bg"])
    fig.suptitle("EQUITY-IMPLIED CREDIT SIGNALS — iTRAXX CROSSOVER CONSTITUENTS",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.35,
                          top=0.93, bottom=0.04, left=0.08, right=0.97)

    names_data = data["names_data"]

    # =========================================================================
    # 1. Composite Credit Signal — All Constituents (left column, full height)
    # =========================================================================
    ax = fig.add_subplot(gs[:, 0])
    names = [n["name"] for n in names_data]
    comps = [n["composite"] for n in names_data]
    signal_colors = []
    for n in names_data:
        if n["signal"] == "STRONG D":
            signal_colors.append(COLORS["red"])
        elif n["signal"] == "DETERIORATING":
            signal_colors.append(COLORS["orange"])
        elif n["signal"] == "NEUTRAL":
            signal_colors.append(COLORS["text_dim"])
        elif n["signal"] == "IMPROVING":
            signal_colors.append(COLORS["cyan"])
        else:
            signal_colors.append(COLORS["green"])

    ax.barh(names, comps, color=signal_colors, alpha=0.85, height=0.7)
    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.8)

    # Signal labels on right
    for i, n in enumerate(names_data):
        label_color = signal_colors[i]
        ax.text(max(comps) + 0.15, i, n["signal"],
                va="center", fontsize=5.5, color=label_color, fontweight="bold")

    style_ax(ax, "Composite Credit Signal — All Constituents",
             "Composite Score")
    ax.tick_params(axis="y", labelsize=6)
    ax.set_xlim(min(comps) - 0.3, max(comps) + 1.2)

    # =========================================================================
    # 2. Signal Summary Box (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")

    summary = (
        f"SIGNAL SUMMARY\n"
        f"{'─' * 30}\n"
        f"Avg Composite: {data['avg_composite']:.3f}\n"
        f"{'─' * 30}\n"
        f"Strong Deter:  {data['strong_d']}\n"
        f"Deteriorating: {data['deteriorating']}\n"
        f"Neutral:       {data['neutral']}\n"
        f"Improving:     {data['improving']}\n"
        f"Strong Improv: {data['strong_improv']}\n"
        f"{'─' * 30}\n"
        f"Weights:\n"
        f" Vol=25%  Mom=25%\n"
        f" DD=20%   Lev=20%\n"
        f" Beta=10%\n"
    )

    summary_color = COLORS["red"] if data["avg_composite"] < -0.3 else \
                    COLORS["green"] if data["avg_composite"] > 0.3 else COLORS["yellow"]
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=summary_color, linewidth=2))
    style_ax(ax, "Signal Summary")

    # =========================================================================
    # 3. Sector Signal Heatmap (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    sector_list = sorted(data["sector_signals"].keys())
    metrics = ["Vol", "Momentum", "Drawdown", "Leverage", "Beta", "Composite"]
    heat = np.zeros((len(sector_list), len(metrics)))
    for i, s in enumerate(sector_list):
        for j, m in enumerate(metrics):
            heat[i, j] = data["sector_signals"][s][m]

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "signals", [COLORS["red"], "#1a1a2e", COLORS["green"]])
    vmax = max(abs(heat.min()), abs(heat.max()), 0.01)
    im = ax.imshow(heat, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(metrics)))
    ax.set_yticks(range(len(sector_list)))
    ax.set_xticklabels(metrics, fontsize=7, rotation=30, ha="right")
    ax.set_yticklabels(sector_list, fontsize=6)
    for i in range(len(sector_list)):
        for j in range(len(metrics)):
            val = heat[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=5, color="white" if abs(val) > vmax * 0.5 else COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.7)
    style_ax(ax, "Sector Signal Heatmap")

    # =========================================================================
    # 4. Average Signal by Type (bottom-center)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1])
    avg_by_type = {}
    for m in ["Vol", "Momentum", "Drawdown", "Leverage", "Beta"]:
        key_map = {"Vol": "vol", "Momentum": "momentum",
                   "Drawdown": "drawdown_z", "Leverage": "leverage", "Beta": "beta"}
        avg_by_type[m] = np.mean([n[key_map[m]] for n in names_data])

    type_names = list(avg_by_type.keys())
    type_vals = [avg_by_type[t] for t in type_names]
    type_colors = [COLORS["green"] if v > 0 else COLORS["red"] for v in type_vals]
    ax.bar(type_names, type_vals, color=type_colors, alpha=0.85)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    for i, (name, val) in enumerate(zip(type_names, type_vals)):
        ax.text(i, val + 0.02 * (1 if val > 0 else -1), f"{val:.2f}",
                ha="center", fontsize=8, color=COLORS["text"])
    style_ax(ax, "Average Signal by Type", ylabel="Avg Z-Score")

    # =========================================================================
    # 5. Signal vs Drawdown scatter (bottom, middle-right area)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 2])
    for n in names_data:
        if n["signal"] == "STRONG D":
            c = COLORS["red"]
        elif n["signal"] == "DETERIORATING":
            c = COLORS["orange"]
        elif n["signal"] == "NEUTRAL":
            c = COLORS["text_dim"]
        elif n["signal"] == "IMPROVING":
            c = COLORS["cyan"]
        else:
            c = COLORS["green"]
        ax.scatter(n["dd_pct"], n["composite"], color=c, alpha=0.7,
                   s=40, edgecolors="white", linewidth=0.3)
        if abs(n["composite"]) > 0.8:
            ax.annotate(n["name"][:10], (n["dd_pct"], n["composite"]),
                        fontsize=5, color=COLORS["text_dim"],
                        textcoords="offset points", xytext=(4, 4))

    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5, linestyle="--")
    ax.axvline(x=-20, color=COLORS["red"], linewidth=0.5, linestyle="--",
               label="DD > 20%")
    style_ax(ax, "Signal vs Drawdown", "Drawdown (%)", "Composite Signal")
    ax.legend(fontsize=7)

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Equity-Implied Credit Signals</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Equity Signal Charts">
</body></html>
"""


@equity_signals_bp.route("/equity-signals")
def equity_signals():
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("equity-signals", generate_equity_signal_charts)
    return render_template_string(TEMPLATE, chart=chart)
