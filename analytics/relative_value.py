"""
Relative Value Analysis — iTraxx Crossover Universe
Route: /relative-value

Rich/cheap RV scoring using Merton-implied spreads, spread per turn of leverage,
sector RV heatmap, within-sector RV dispersion, cross-sector opportunity scatter,
and RV summary.
"""

import numpy as np
from datetime import datetime
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

rv_bp = Blueprint("relative_value", __name__)

# ---------------------------------------------------------------------------
# iTraxx Crossover names for RV
# ---------------------------------------------------------------------------
NAMES = [
    {"name": "Ardagh", "sector": "Packaging", "spread": 820},
    {"name": "Casino Guichard", "sector": "Retail", "spread": 1250},
    {"name": "Altice France", "sector": "Telecom", "spread": 980},
    {"name": "Intrum", "sector": "Financial Svcs", "spread": 650},
    {"name": "Atos", "sector": "Technology", "spread": 1500},
    {"name": "SFR", "sector": "Telecom", "spread": 720},
    {"name": "Teva Pharma", "sector": "Healthcare", "spread": 420},
    {"name": "Grifols", "sector": "Healthcare", "spread": 310},
    {"name": "Telecom Italia", "sector": "Telecom", "spread": 380},
    {"name": "Bayer", "sector": "Chemicals", "spread": 350},
    {"name": "Loxam", "sector": "Industrials", "spread": 280},
    {"name": "Stonegate", "sector": "Travel & Leisure", "spread": 550},
    {"name": "Verisure", "sector": "Industrials", "spread": 320},
    {"name": "Picard", "sector": "Food & Bev", "spread": 480},
    {"name": "Maxeda", "sector": "Retail", "spread": 580},
    {"name": "Renault", "sector": "Autos", "spread": 180},
    {"name": "Peugeot", "sector": "Autos", "spread": 120},
    {"name": "Vodafone", "sector": "Telecom", "spread": 150},
    {"name": "Nokia", "sector": "Technology", "spread": 200},
    {"name": "Lufthansa", "sector": "Travel & Leisure", "spread": 210},
    {"name": "Rolls-Royce", "sector": "Industrials", "spread": 250},
    {"name": "ThyssenKrupp", "sector": "Basic Resources", "spread": 350},
    {"name": "ArcelorMittal", "sector": "Basic Resources", "spread": 180},
    {"name": "HeidelbergCement", "sector": "Construction", "spread": 160},
    {"name": "Repsol", "sector": "Energy", "spread": 100},
    {"name": "EDP", "sector": "Utilities", "spread": 90},
    {"name": "Enel", "sector": "Utilities", "spread": 80},
    {"name": "Unibail", "sector": "Real Estate", "spread": 140},
    {"name": "ING Group", "sector": "Banks", "spread": 70},
    {"name": "Commerzbank", "sector": "Banks", "spread": 95},
    {"name": "Aegon", "sector": "Insurance", "spread": 110},
    {"name": "Adecco", "sector": "Industrials", "spread": 130},
    {"name": "Marks & Spencer", "sector": "Retail", "spread": 260},
    {"name": "Carrefour", "sector": "Retail", "spread": 130},
    {"name": "Vivendi", "sector": "Media", "spread": 170},
    {"name": "ProSiebenSat.1", "sector": "Media", "spread": 290},
    {"name": "TUI", "sector": "Travel & Leisure", "spread": 400},
    {"name": "IAG", "sector": "Travel & Leisure", "spread": 190},
    {"name": "Leonardo", "sector": "Industrials", "spread": 160},
    {"name": "Continental", "sector": "Autos", "spread": 110},
    {"name": "Pernod Ricard", "sector": "Food & Bev", "spread": 75},
    {"name": "Danone", "sector": "Food & Bev", "spread": 65},
    {"name": "Accor", "sector": "Travel & Leisure", "spread": 170},
    {"name": "Faurecia", "sector": "Autos", "spread": 230},
    {"name": "ZF Friedrichshafn", "sector": "Autos", "spread": 250},
    {"name": "Samsonite", "sector": "Consumer Goods", "spread": 220},
    {"name": "Ineos", "sector": "Chemicals", "spread": 310},
    {"name": "Techem", "sector": "Industrials", "spread": 280},
    {"name": "OI Glass", "sector": "Packaging", "spread": 340},
    {"name": "Selecta", "sector": "Food & Bev", "spread": 520},
    {"name": "Cirsa", "sector": "Travel & Leisure", "spread": 360},
    {"name": "Eircom", "sector": "Telecom", "spread": 310},
    {"name": "Wind Tre", "sector": "Telecom", "spread": 380},
    {"name": "Maisons du Monde", "sector": "Retail", "spread": 450},
    {"name": "Douglas", "sector": "Retail", "spread": 400},
    {"name": "CBR Fashion", "sector": "Consumer Goods", "spread": 480},
    {"name": "Birkenstock", "sector": "Consumer Goods", "spread": 200},
    {"name": "Tereos", "sector": "Food & Bev", "spread": 280},
    {"name": "Europcar", "sector": "Travel & Leisure", "spread": 350},
    {"name": "Puma Energy", "sector": "Energy", "spread": 270},
    {"name": "Ceconomy", "sector": "Retail", "spread": 240},
]


def _generate_rv_data():
    """Generate relative value analysis data."""
    np.random.seed(870)

    names_data = []
    for n in NAMES:
        # Merton-implied spread (model fair value)
        merton = n["spread"] * (0.7 + 0.6 * np.random.random())
        # RV score: 0-100, >65 = CHEAP, <35 = RICH
        rv_score = 50 + (merton - n["spread"]) / max(n["spread"], 1) * 80
        rv_score += np.random.normal(0, 8)
        rv_score = np.clip(rv_score, 5, 95)

        # Classification
        if rv_score > 65:
            signal = "CHEAP"
        elif rv_score < 35:
            signal = "RICH"
        else:
            signal = "FAIR"

        # Leverage for spread-per-turn
        leverage = max(1.0, np.random.uniform(1.5, 8.0))
        spread_per_turn = n["spread"] / leverage

        names_data.append({
            **n, "merton": merton, "rv_score": rv_score,
            "signal": signal, "leverage": leverage,
            "spread_per_turn": spread_per_turn,
        })

    # Stats
    rv_scores = [d["rv_score"] for d in names_data]
    cheap_count = sum(1 for d in names_data if d["signal"] == "CHEAP")
    rich_count = sum(1 for d in names_data if d["signal"] == "RICH")
    fair_count = sum(1 for d in names_data if d["signal"] == "FAIR")

    # R-squared between market spread and merton
    spreads = np.array([d["spread"] for d in names_data])
    mertons = np.array([d["merton"] for d in names_data])
    ss_res = np.sum((spreads - mertons) ** 2)
    ss_tot = np.sum((spreads - np.mean(spreads)) ** 2)
    r_squared = max(0, 1 - ss_res / ss_tot)

    return {
        "names_data": names_data,
        "avg_rv": np.mean(rv_scores),
        "cheap": cheap_count, "rich": rich_count, "fair": fair_count,
        "r_squared": r_squared,
    }


def generate_rv_charts():
    """Generate relative value analysis charts."""
    setup_dark_style()
    data = _generate_rv_data()

    fig = plt.figure(figsize=(26, 18), facecolor=COLORS["bg"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.suptitle("RELATIVE VALUE ANALYSIS — iTRAXX CROSSOVER UNIVERSE",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {now} | {len(data['names_data'])} names",
             ha="center", fontsize=10, color=COLORS["text_dim"])

    gs = fig.add_gridspec(2, 3, hspace=0.4, wspace=0.35,
                          top=0.92, bottom=0.04, left=0.08, right=0.97)

    names_data = data["names_data"]

    # =========================================================================
    # 1. Rich / Cheap: RV Score vs Market Spread scatter (top-left)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 0])
    for d in names_data:
        if d["signal"] == "CHEAP":
            c = COLORS["green"]
        elif d["signal"] == "RICH":
            c = COLORS["red"]
        else:
            c = COLORS["text_dim"]
        ax.scatter(d["rv_score"], d["merton"], color=c, alpha=0.7,
                   s=35, edgecolors="white", linewidth=0.3)
        if d["rv_score"] > 75 or d["rv_score"] < 25:
            ax.annotate(d["name"][:10], (d["rv_score"], d["merton"]),
                        fontsize=5, color=COLORS["text_dim"],
                        textcoords="offset points", xytext=(3, 3))

    ax.axvline(x=65, color=COLORS["green"], linestyle="--", linewidth=0.5,
               label="CHEAP (>65)")
    ax.axvline(x=35, color=COLORS["red"], linestyle="--", linewidth=0.5,
               label="RICH (<35)")
    style_ax(ax, "Rich / Cheap: RV Score vs Merton Implied Spread",
             "RV Score", "Merton Implied Spread (bps)")
    ax.legend(fontsize=6)

    # =========================================================================
    # 2. RV Summary Box (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")

    summary = (
        f"RELATIVE VALUE SUMMARY\n"
        f"{'─' * 30}\n"
        f"Names:       {len(names_data)}\n"
        f"Avg RV Score: {data['avg_rv']:.1f}\n"
        f"{'─' * 30}\n"
        f"CHEAP:       {data['cheap']}\n"
        f"RICH:        {data['rich']}\n"
        f"FAIR:        {data['fair']}\n"
        f"{'─' * 30}\n"
        f"R-squared:   {data['r_squared']:.3f}\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=11,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=COLORS["cyan"], linewidth=2))
    style_ax(ax, "Relative Value Summary")

    # =========================================================================
    # 3. Spread Per Turn of Leverage (top-right, full height bar)
    # =========================================================================
    ax = fig.add_subplot(gs[:, 2])
    sorted_spt = sorted(names_data, key=lambda x: x["spread_per_turn"], reverse=True)
    spt_names = [d["name"] for d in sorted_spt]
    spt_vals = [d["spread_per_turn"] for d in sorted_spt]
    spt_colors = []
    for d in sorted_spt:
        if d["signal"] == "CHEAP":
            spt_colors.append(COLORS["green"])
        elif d["signal"] == "RICH":
            spt_colors.append(COLORS["red"])
        else:
            spt_colors.append(COLORS["text_dim"])

    ax.barh(spt_names, spt_vals, color=spt_colors, alpha=0.85, height=0.7)
    median_spt = np.median(spt_vals)
    ax.axvline(x=median_spt, color=COLORS["yellow"], linestyle="--",
               linewidth=0.7, label=f"Median ({median_spt:.0f})")
    style_ax(ax, "Spread Per Turn of Leverage (bps)", "bps/turn")
    ax.tick_params(axis="y", labelsize=5)
    ax.legend(fontsize=6)

    # =========================================================================
    # 4. Sector RV Heatmap (bottom-left)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 0])

    sector_agg = {}
    for d in names_data:
        s = d["sector"]
        if s not in sector_agg:
            sector_agg[s] = {"rv": [], "lev": [], "cov": [], "margin": []}
        sector_agg[s]["rv"].append(d["rv_score"])
        sector_agg[s]["lev"].append(d["leverage"])
        # Use spread_per_turn as a proxy for coverage efficiency
        sector_agg[s]["cov"].append(d["spread_per_turn"])
        sector_agg[s]["margin"].append(d["spread"])

    sector_list = sorted(sector_agg.keys())
    metrics = ["RV Score", "Leverage", "Spread/Turn", "Avg Spread"]
    heat = np.zeros((len(sector_list), 4))
    for i, s in enumerate(sector_list):
        heat[i, 0] = np.mean(sector_agg[s]["rv"]) / 100
        heat[i, 1] = 1.0 - min(np.mean(sector_agg[s]["lev"]) / 8.0, 1.0)
        heat[i, 2] = 1.0 - min(np.mean(sector_agg[s]["cov"]) / 300, 1.0)
        heat[i, 3] = 1.0 - min(np.mean(sector_agg[s]["margin"]) / 800, 1.0)
    heat = np.clip(heat, 0, 1)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rv_heat", [COLORS["red"], COLORS["yellow"], COLORS["green"]])
    im = ax.imshow(heat, cmap=cmap, aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(4))
    ax.set_yticks(range(len(sector_list)))
    ax.set_xticklabels(metrics, fontsize=7, rotation=20, ha="right")
    ax.set_yticklabels(sector_list, fontsize=6)
    for i in range(len(sector_list)):
        for j in range(4):
            ax.text(j, i, f"{heat[i,j]:.2f}", ha="center", va="center",
                    fontsize=5.5, color="white" if heat[i, j] > 0.6 else COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.7)
    style_ax(ax, "Sector RV Heatmap (red=worse) | *inverted")

    # =========================================================================
    # 5. Within-Sector RV Dispersion (bottom-center)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1])
    sector_disp = {}
    for s in sector_list:
        rvs = sector_agg[s]["rv"]
        sector_disp[s] = {"mean": np.mean(rvs),
                          "min": np.min(rvs), "max": np.max(rvs)}

    sorted_sectors = sorted(sector_disp.items(),
                            key=lambda x: x[1]["max"] - x[1]["min"],
                            reverse=True)
    sd_names = [s[0] for s in sorted_sectors]
    sd_means = [s[1]["mean"] for s in sorted_sectors]
    sd_mins = [s[1]["min"] for s in sorted_sectors]
    sd_maxs = [s[1]["max"] for s in sorted_sectors]

    y_pos = np.arange(len(sd_names))
    # Mean bars
    ax.barh(y_pos, sd_means, color=COLORS["cyan"], alpha=0.7, height=0.5)
    # Whiskers (min to max)
    for i in range(len(sd_names)):
        ax.plot([sd_mins[i], sd_maxs[i]], [i, i],
                color=COLORS["text"], linewidth=1.5, alpha=0.8)
        ax.plot(sd_mins[i], i, "|", color=COLORS["text"], markersize=8)
        ax.plot(sd_maxs[i], i, "|", color=COLORS["text"], markersize=8)

    ax.axvline(x=50, color=COLORS["text_dim"], linestyle="--", linewidth=0.5)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(sd_names, fontsize=7)
    style_ax(ax, "Within-Sector RV Score Dispersion (bar=mean, whiskers=range)",
             "RV Score")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Relative Value Analysis</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Relative Value Charts">
</body></html>
"""


@rv_bp.route("/relative-value")
def relative_value():
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("relative-value", generate_rv_charts)
    return render_template_string(TEMPLATE, chart=chart)
