"""
Distressed / LME Monitor - iTraxx Crossover Universe
Route: /distressed

Monitors liquidity stress scores, cash burn timelines, distress scatter,
and sector distress heatmaps for the iTraxx Crossover universe.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

distressed_bp = Blueprint("distressed_monitor", __name__)

# ---------------------------------------------------------------------------
# iTraxx Crossover distressed universe
# ---------------------------------------------------------------------------
DISTRESSED_NAMES = [
    {"name": "Ardagh", "sector": "Packaging", "cds": 820, "liq_score": 8.2,
     "mkt_distress": 7.5, "cash_burn_months": 14, "rating": "CCC+"},
    {"name": "Casino Guichard", "sector": "Retail", "cds": 1250, "liq_score": 9.1,
     "mkt_distress": 8.8, "cash_burn_months": 8, "rating": "CCC"},
    {"name": "Altice France", "sector": "Telecom", "cds": 980, "liq_score": 7.8,
     "mkt_distress": 7.2, "cash_burn_months": 18, "rating": "CCC+"},
    {"name": "Intrum", "sector": "Financials", "cds": 650, "liq_score": 6.5,
     "mkt_distress": 5.8, "cash_burn_months": 22, "rating": "B-"},
    {"name": "Atos", "sector": "Tech", "cds": 1500, "liq_score": 9.5,
     "mkt_distress": 9.2, "cash_burn_months": 6, "rating": "CC"},
    {"name": "SFR", "sector": "Telecom", "cds": 720, "liq_score": 7.0,
     "mkt_distress": 6.5, "cash_burn_months": 20, "rating": "B"},
    {"name": "Teva Pharma", "sector": "Healthcare", "cds": 420, "liq_score": 5.2,
     "mkt_distress": 4.5, "cash_burn_months": 30, "rating": "BB-"},
    {"name": "Grifols", "sector": "Healthcare", "cds": 310, "liq_score": 4.5,
     "mkt_distress": 3.8, "cash_burn_months": 36, "rating": "BB"},
    {"name": "Telecom Italia", "sector": "Telecom", "cds": 380, "liq_score": 4.8,
     "mkt_distress": 4.2, "cash_burn_months": 28, "rating": "BB-"},
    {"name": "Bayer", "sector": "Chemicals", "cds": 350, "liq_score": 4.2,
     "mkt_distress": 3.5, "cash_burn_months": 40, "rating": "BBB-"},
    {"name": "Loxam", "sector": "Industrials", "cds": 280, "liq_score": 3.8,
     "mkt_distress": 3.2, "cash_burn_months": 42, "rating": "BB"},
    {"name": "Stonegate", "sector": "Leisure", "cds": 550, "liq_score": 6.0,
     "mkt_distress": 5.5, "cash_burn_months": 24, "rating": "B"},
    {"name": "Verisure", "sector": "Services", "cds": 320, "liq_score": 4.0,
     "mkt_distress": 3.5, "cash_burn_months": 38, "rating": "BB-"},
    {"name": "Picard", "sector": "Retail", "cds": 480, "liq_score": 5.5,
     "mkt_distress": 5.0, "cash_burn_months": 26, "rating": "B"},
    {"name": "Maxeda", "sector": "Retail", "cds": 580, "liq_score": 6.2,
     "mkt_distress": 5.8, "cash_burn_months": 20, "rating": "B-"},
]

SECTORS = list(set(d["sector"] for d in DISTRESSED_NAMES))


def generate_distressed_charts():
    """Generate distressed / LME monitor charts."""
    setup_dark_style()

    fig = plt.figure(figsize=(22, 16), facecolor=COLORS["bg"])
    fig.suptitle("DISTRESSED / LME MONITOR — iTRAXX CROSSOVER UNIVERSE",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35,
                          top=0.93, bottom=0.06, left=0.06, right=0.97)

    # 1. Liquidity Stress Scores (horizontal bar)
    ax = fig.add_subplot(gs[0, 0])
    sorted_names = sorted(DISTRESSED_NAMES, key=lambda x: x["liq_score"], reverse=True)
    names = [d["name"] for d in sorted_names]
    scores = [d["liq_score"] for d in sorted_names]
    colors = [COLORS["red"] if s > 7 else COLORS["orange"] if s > 5
              else COLORS["green"] for s in scores]
    ax.barh(names, scores, color=colors, alpha=0.85)
    ax.axvline(x=7, color=COLORS["red"], linestyle="--", linewidth=0.8, label="Critical")
    ax.axvline(x=5, color=COLORS["orange"], linestyle="--", linewidth=0.8, label="Elevated")
    for i, (name, score) in enumerate(zip(names, scores)):
        ax.text(score + 0.1, i, f"{score:.1f}", va="center", fontsize=7,
                color=COLORS["text"])
    style_ax(ax, "Liquidity Stress Score", "Score (0-10)")
    ax.set_xlim(0, 11)
    ax.tick_params(axis="y", labelsize=7)
    ax.legend(fontsize=7)

    # 2. Distress Summary table
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")
    critical = sum(1 for d in DISTRESSED_NAMES if d["liq_score"] > 7)
    elevated = sum(1 for d in DISTRESSED_NAMES if 5 < d["liq_score"] <= 7)
    monitor = sum(1 for d in DISTRESSED_NAMES if d["liq_score"] <= 5)
    avg_cds = np.mean([d["cds"] for d in DISTRESSED_NAMES])
    max_cds_name = max(DISTRESSED_NAMES, key=lambda x: x["cds"])

    summary = (
        f"DISTRESS SUMMARY\n"
        f"{'─' * 32}\n"
        f"Universe: {len(DISTRESSED_NAMES)} names\n"
        f"{'─' * 32}\n"
        f"Critical (>7):  {critical}\n"
        f"Elevated (5-7): {elevated}\n"
        f"Monitor  (<5):  {monitor}\n"
        f"{'─' * 32}\n"
        f"Avg CDS: {avg_cds:.0f} bps\n"
        f"Widest: {max_cds_name['name']} ({max_cds_name['cds']}bp)\n"
        f"{'─' * 32}\n"
        f"LME candidates: {critical}\n"
        f"Watch list: {elevated}"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=COLORS["red"], linewidth=1.5))
    style_ax(ax, "Distress Summary")

    # 3. Cash Burn Timeline
    ax = fig.add_subplot(gs[0, 2])
    sorted_cb = sorted(DISTRESSED_NAMES, key=lambda x: x["cash_burn_months"])
    names_cb = [d["name"] for d in sorted_cb]
    months_cb = [d["cash_burn_months"] for d in sorted_cb]
    colors_cb = [COLORS["red"] if m < 12 else COLORS["orange"] if m < 24
                 else COLORS["green"] for m in months_cb]
    ax.barh(names_cb, months_cb, color=colors_cb, alpha=0.85)
    ax.axvline(x=12, color=COLORS["red"], linestyle="--", linewidth=0.8, label="<12m Critical")
    ax.axvline(x=24, color=COLORS["orange"], linestyle="--", linewidth=0.8, label="<24m Watch")
    style_ax(ax, "Cash Burn Timeline", "Months of Runway")
    ax.tick_params(axis="y", labelsize=7)
    ax.legend(fontsize=7)

    # 4. Score Distribution
    ax = fig.add_subplot(gs[1, 0])
    all_scores = [d["liq_score"] for d in DISTRESSED_NAMES]
    bins = np.arange(0, 11, 1)
    n, _, patches = ax.hist(all_scores, bins=bins, color=COLORS["cyan"],
                            alpha=0.7, edgecolor=COLORS["grid"])
    for patch, left_edge in zip(patches, bins[:-1]):
        if left_edge >= 7:
            patch.set_facecolor(COLORS["red"])
        elif left_edge >= 5:
            patch.set_facecolor(COLORS["orange"])
        else:
            patch.set_facecolor(COLORS["green"])
        patch.set_alpha(0.8)
    style_ax(ax, "Liquidity Score Distribution", "Score", "Count")

    # 5. Liquidity vs Market Distress scatter
    ax = fig.add_subplot(gs[1, 1])
    for i, d in enumerate(DISTRESSED_NAMES):
        size = d["cds"] / 5
        color = COLORS["red"] if d["liq_score"] > 7 else \
                COLORS["orange"] if d["liq_score"] > 5 else COLORS["green"]
        ax.scatter(d["mkt_distress"], d["liq_score"], s=size,
                   color=color, alpha=0.7, edgecolors="white", linewidth=0.5)
        ax.annotate(d["name"][:8], (d["mkt_distress"], d["liq_score"]),
                    fontsize=6, color=COLORS["text_dim"],
                    textcoords="offset points", xytext=(5, 5))
    # Quadrant lines
    ax.axhline(y=7, color=COLORS["red"], linestyle="--", linewidth=0.5)
    ax.axvline(x=7, color=COLORS["red"], linestyle="--", linewidth=0.5)
    ax.text(8.5, 9, "LME\nZone", ha="center", fontsize=9, color=COLORS["red"],
            fontweight="bold")
    style_ax(ax, "Liquidity vs Market Distress",
             "Market Distress Score", "Liquidity Stress Score")

    # 6. Sector Distress Map (heatmap)
    ax = fig.add_subplot(gs[1, 2])
    sector_data = {}
    for d in DISTRESSED_NAMES:
        if d["sector"] not in sector_data:
            sector_data[d["sector"]] = {"scores": [], "cds": []}
        sector_data[d["sector"]]["scores"].append(d["liq_score"])
        sector_data[d["sector"]]["cds"].append(d["cds"])

    sector_names = sorted(sector_data.keys())
    metrics = ["Avg Liq Score", "Max Liq Score", "Avg CDS", "# Names"]
    heat_data = np.zeros((len(sector_names), len(metrics)))

    for i, s in enumerate(sector_names):
        scores = sector_data[s]["scores"]
        cds_vals = sector_data[s]["cds"]
        heat_data[i, 0] = np.mean(scores) / 10  # Normalize
        heat_data[i, 1] = np.max(scores) / 10
        heat_data[i, 2] = np.mean(cds_vals) / 1500
        heat_data[i, 3] = len(scores) / 5

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "distress", [COLORS["green"], COLORS["yellow"], COLORS["red"]])
    im = ax.imshow(heat_data, cmap=cmap, aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(metrics)))
    ax.set_yticks(range(len(sector_names)))
    ax.set_xticklabels(metrics, fontsize=7, rotation=30, ha="right")
    ax.set_yticklabels(sector_names, fontsize=7)
    for i in range(len(sector_names)):
        for j in range(len(metrics)):
            ax.text(j, i, f"{heat_data[i, j]:.2f}", ha="center", va="center",
                    fontsize=7, color="white" if heat_data[i, j] > 0.5 else COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.8)
    style_ax(ax, "Sector Distress Heatmap")

    # 7. Full universe table
    ax = fig.add_subplot(gs[2, :])
    ax.axis("off")
    col_labels = ["Name", "Sector", "Rating", "CDS (bps)", "Liq Score",
                  "Mkt Distress", "Cash Burn (m)", "Status"]
    table_data = []
    for d in sorted(DISTRESSED_NAMES, key=lambda x: x["liq_score"], reverse=True):
        status = "CRITICAL" if d["liq_score"] > 7 else \
                 "ELEVATED" if d["liq_score"] > 5 else "MONITOR"
        table_data.append([
            d["name"], d["sector"], d["rating"], str(d["cds"]),
            f"{d['liq_score']:.1f}", f"{d['mkt_distress']:.1f}",
            str(d["cash_burn_months"]), status
        ])

    table = ax.table(cellText=table_data, colLabels=col_labels,
                     cellLoc="center", loc="center",
                     colColours=[COLORS["panel"]] * len(col_labels))
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)

    for key, cell in table.get_celld().items():
        cell.set_edgecolor(COLORS["grid"])
        if key[0] == 0:
            cell.set_facecolor(COLORS["purple"])
            cell.set_text_props(color="white", fontweight="bold")
        else:
            cell.set_facecolor(COLORS["panel"])
            cell.set_text_props(color=COLORS["text"])
            if key[1] == 7:  # Status column
                text = cell.get_text().get_text()
                if text == "CRITICAL":
                    cell.set_text_props(color=COLORS["red"], fontweight="bold")
                elif text == "ELEVATED":
                    cell.set_text_props(color=COLORS["orange"])
                else:
                    cell.set_text_props(color=COLORS["green"])

    style_ax(ax, "iTraxx Crossover — Distressed Universe")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Distressed / LME Monitor</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1600px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Distressed Monitor Charts">
</body></html>
"""


@distressed_bp.route("/distressed")
def distressed():
    chart = generate_distressed_charts()
    return render_template_string(TEMPLATE, chart=chart)
