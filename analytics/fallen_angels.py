"""
Fallen Angel / Rising Star Screener — iTraxx Crossover
Route: /fallen-angels

FA scoring from DD Level, DD Trajectory, Eq Momentum, Leverage/Vol,
Sector Stress. Rising Star scoring from inverse metrics. Dual bar chart,
component breakdowns, FA vs DD scatter, sector risk map, and alert table.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

fallen_angels_bp = Blueprint("fallen_angels", __name__)

# ---------------------------------------------------------------------------
# iTraxx Crossover universe for FA/RS screening (~61 names)
# ---------------------------------------------------------------------------
NAMES = [
    {"name": "Ardagh", "rating": "CCC+", "sector": "Basic Resources"},
    {"name": "Casino Guichard", "rating": "CCC", "sector": "Retail"},
    {"name": "Altice France", "rating": "CCC+", "sector": "Telecom"},
    {"name": "Intrum", "rating": "B-", "sector": "Financial Services"},
    {"name": "Atos", "rating": "CC", "sector": "Technology"},
    {"name": "SFR", "rating": "B", "sector": "Telecom"},
    {"name": "Teva Pharma", "rating": "BB-", "sector": "Healthcare"},
    {"name": "Grifols", "rating": "BB", "sector": "Healthcare"},
    {"name": "Telecom Italia", "rating": "BB-", "sector": "Telecom"},
    {"name": "Bayer", "rating": "BBB-", "sector": "Chemicals"},
    {"name": "Loxam", "rating": "BB", "sector": "Industrials"},
    {"name": "Stonegate", "rating": "B", "sector": "Travel & Leisure"},
    {"name": "Verisure", "rating": "BB-", "sector": "Industrials"},
    {"name": "Picard", "rating": "B", "sector": "Food & Beverage"},
    {"name": "Maxeda", "rating": "B-", "sector": "Retail"},
    {"name": "Renault", "rating": "BBB-", "sector": "Autos"},
    {"name": "Peugeot", "rating": "BBB", "sector": "Autos"},
    {"name": "Vodafone", "rating": "BBB", "sector": "Telecom"},
    {"name": "Nokia", "rating": "BBB-", "sector": "Technology"},
    {"name": "Lufthansa", "rating": "BBB-", "sector": "Travel & Leisure"},
    {"name": "Rolls-Royce", "rating": "BB+", "sector": "Industrials"},
    {"name": "ThyssenKrupp", "rating": "BB-", "sector": "Basic Resources"},
    {"name": "ArcelorMittal", "rating": "BBB-", "sector": "Basic Resources"},
    {"name": "Heidelberg Cement", "rating": "BBB-", "sector": "Construction"},
    {"name": "Repsol", "rating": "BBB", "sector": "Energy"},
    {"name": "EDP", "rating": "BBB", "sector": "Utilities"},
    {"name": "Enel", "rating": "BBB+", "sector": "Utilities"},
    {"name": "Unibail", "rating": "BBB+", "sector": "Real Estate"},
    {"name": "ING Group", "rating": "A-", "sector": "Banks"},
    {"name": "Commerzbank", "rating": "BBB+", "sector": "Banks"},
    {"name": "Aegon", "rating": "BBB", "sector": "Insurance"},
    {"name": "Adecco", "rating": "BBB", "sector": "Industrials"},
    {"name": "Marks & Spencer", "rating": "BB+", "sector": "Retail"},
    {"name": "Carrefour", "rating": "BBB", "sector": "Retail"},
    {"name": "Vivendi", "rating": "BBB-", "sector": "Media"},
    {"name": "ProSiebenSat.1", "rating": "BB+", "sector": "Media"},
    {"name": "TUI", "rating": "B+", "sector": "Travel & Leisure"},
    {"name": "IAG", "rating": "BBB-", "sector": "Travel & Leisure"},
    {"name": "Leonardo", "rating": "BBB-", "sector": "Industrials"},
    {"name": "Continental", "rating": "BBB", "sector": "Autos"},
    {"name": "Pernod Ricard", "rating": "BBB+", "sector": "Food & Beverage"},
    {"name": "Danone", "rating": "BBB+", "sector": "Food & Beverage"},
    {"name": "Accor", "rating": "BBB-", "sector": "Travel & Leisure"},
    {"name": "Faurecia", "rating": "BB+", "sector": "Autos"},
    {"name": "ZF Friedrichshafen", "rating": "BB+", "sector": "Autos"},
    {"name": "Samsonite", "rating": "BB+", "sector": "Consumer Goods"},
    {"name": "Ineos", "rating": "BB", "sector": "Chemicals"},
    {"name": "Techem", "rating": "BB-", "sector": "Industrials"},
    {"name": "OI Glass", "rating": "BB-", "sector": "Basic Resources"},
    {"name": "Selecta", "rating": "B-", "sector": "Food & Beverage"},
    {"name": "Cirsa", "rating": "B+", "sector": "Travel & Leisure"},
    {"name": "Eircom", "rating": "BB-", "sector": "Telecom"},
    {"name": "Wind Tre", "rating": "B+", "sector": "Telecom"},
    {"name": "Maisons du Monde", "rating": "B", "sector": "Retail"},
    {"name": "Douglas", "rating": "B", "sector": "Retail"},
    {"name": "CBR Fashion", "rating": "B-", "sector": "Consumer Goods"},
    {"name": "Birkenstock", "rating": "BB", "sector": "Consumer Goods"},
    {"name": "Tereos", "rating": "BB-", "sector": "Food & Beverage"},
    {"name": "Europcar", "rating": "B+", "sector": "Travel & Leisure"},
    {"name": "Puma Energy", "rating": "BB-", "sector": "Energy"},
    {"name": "Ceconomy", "rating": "BB", "sector": "Retail"},
]


def _rating_to_numeric(rating):
    """Convert rating string to numeric for distance-to-default proxy."""
    scale = {
        "CC": 1, "CCC": 2, "CCC+": 3, "B-": 4, "B": 5, "B+": 6,
        "BB-": 7, "BB": 8, "BB+": 9, "BBB-": 10, "BBB": 11,
        "BBB+": 12, "A-": 13, "A": 14,
    }
    return scale.get(rating, 8)


def _generate_fa_rs_data():
    """Generate fallen angel / rising star screening data."""
    np.random.seed(777)

    names_data = []
    for n in NAMES:
        rating_num = _rating_to_numeric(n["rating"])

        # Distance to default (higher = safer; correlates with rating)
        dd = max(rating_num * 0.6 + np.random.normal(0, 1.5), 0.5)

        # FA component scores (0-100; higher = more FA risk)
        dd_level = max(0, min(100, 80 - dd * 8 + np.random.normal(0, 10)))
        dd_traj = max(0, min(100, np.random.normal(40, 20)))
        eq_mom = max(0, min(100, np.random.normal(35, 18)))
        lev_vol = max(0, min(100, 60 - rating_num * 3 + np.random.normal(0, 12)))
        sector_stress = max(0, min(100, np.random.normal(30, 15)))

        fa_score = (0.25 * dd_level + 0.20 * dd_traj + 0.20 * eq_mom +
                    0.20 * lev_vol + 0.15 * sector_stress)

        # RS component scores (0-100; higher = more RS potential)
        rs_score = max(0, min(100, 100 - fa_score + np.random.normal(0, 15)))

        # Alert classification
        if fa_score >= 60:
            alert = "HIGH RISK"
        elif fa_score >= 40:
            alert = "WATCH LIST"
        elif rs_score >= 60:
            alert = "RS STRONG"
        elif rs_score >= 45:
            alert = "RS POSSIBLE"
        else:
            alert = "MONITOR"

        names_data.append({
            "name": n["name"], "rating": n["rating"], "sector": n["sector"],
            "dd": dd, "fa_score": fa_score, "rs_score": rs_score,
            "dd_level": dd_level, "dd_traj": dd_traj,
            "eq_mom": eq_mom, "lev_vol": lev_vol,
            "sector_stress": sector_stress, "alert": alert,
        })

    # Sort by FA score descending
    names_data.sort(key=lambda x: x["fa_score"], reverse=True)

    # Summary stats
    fa_scores = [n["fa_score"] for n in names_data]
    rs_scores = [n["rs_score"] for n in names_data]
    fa_high = sum(1 for n in names_data if n["alert"] == "HIGH RISK")
    fa_watch = sum(1 for n in names_data if n["alert"] == "WATCH LIST")
    rs_strong = sum(1 for n in names_data if n["alert"] == "RS STRONG")
    rs_possible = sum(1 for n in names_data if n["alert"] == "RS POSSIBLE")

    return {
        "names_data": names_data,
        "avg_fa": np.mean(fa_scores), "avg_rs": np.mean(rs_scores),
        "fa_high": fa_high, "fa_watch": fa_watch,
        "rs_strong": rs_strong, "rs_possible": rs_possible,
    }


def generate_fallen_angel_charts():
    """Generate fallen angel / rising star screener charts."""
    setup_dark_style()
    data = _generate_fa_rs_data()

    fig = plt.figure(figsize=(26, 20), facecolor=COLORS["bg"])
    fig.suptitle("FALLEN ANGEL / RISING STAR SCREENER — iTRAXX CROSSOVER",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(3, 3, hspace=0.4, wspace=0.35,
                          top=0.93, bottom=0.04, left=0.08, right=0.97)

    names_data = data["names_data"]

    # =========================================================================
    # 1. FA Risk vs RS Potential — dual horizontal bar (left column, full)
    # =========================================================================
    ax = fig.add_subplot(gs[:2, 0])
    names = [n["name"] for n in names_data]
    fa_vals = [n["fa_score"] for n in names_data]
    rs_vals = [-n["rs_score"] for n in names_data]  # Negative for left side

    y_pos = np.arange(len(names))
    ax.barh(y_pos, fa_vals, color=COLORS["red"], alpha=0.7, height=0.4,
            label="FA Risk")
    ax.barh(y_pos - 0.4, rs_vals, color=COLORS["green"], alpha=0.7, height=0.4,
            label="RS Potential")
    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.8)
    ax.axvline(x=60, color=COLORS["red"], linestyle="--", linewidth=0.5,
               alpha=0.5, label="FA High Risk (60)")
    ax.axvline(x=-60, color=COLORS["green"], linestyle="--", linewidth=0.5,
               alpha=0.5, label="RS Strong (60)")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=5)
    style_ax(ax, "Fallen Angel Risk vs Rising Star Potential",
             "← RS Potential | FA Risk →")
    ax.legend(fontsize=6, loc="upper right")

    # =========================================================================
    # 2. Screener Summary Box (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")
    summary = (
        f"SCREENER SUMMARY\n"
        f"{'─' * 30}\n"
        f"Avg FA Score: {data['avg_fa']:.1f}\n"
        f"FA High Risk: {data['fa_high']}\n"
        f"FA Watch List: {data['fa_watch']}\n"
        f"{'─' * 30}\n"
        f"Avg RS Score: {data['avg_rs']:.1f}\n"
        f"RS Strong: {data['rs_strong']}\n"
        f"RS Possible: {data['rs_possible']}\n"
        f"{'─' * 30}\n"
        f"FA High Risk >= 60\n"
        f"RS Strong >= 60\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=COLORS["orange"], linewidth=2))
    style_ax(ax, "Screener Summary")

    # =========================================================================
    # 3. Top 15 FA Risk — Component Breakdown (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    top15 = names_data[:15]
    t_names = [n["name"] for n in top15]
    y_pos = np.arange(len(t_names))

    # Stacked horizontal bars
    components = ["dd_level", "dd_traj", "eq_mom", "lev_vol", "sector_stress"]
    comp_labels = ["DD Level", "DD Trajectory", "Eq Momentum",
                   "Leverage/Vol", "Sector Stress"]
    comp_colors = [COLORS["red"], COLORS["orange"], COLORS["yellow"],
                   COLORS["purple"], COLORS["blue"]]

    left = np.zeros(len(top15))
    for ci, (comp, label, color) in enumerate(zip(components, comp_labels, comp_colors)):
        vals = [n[comp] * (0.25 if ci == 0 else 0.20 if ci < 4 else 0.15)
                for n in top15]
        ax.barh(y_pos, vals, left=left, color=color, alpha=0.8,
                label=label, height=0.6)
        left += vals

    ax.set_yticks(y_pos)
    ax.set_yticklabels(t_names, fontsize=6)
    style_ax(ax, "Top 15 Fallen Angel Risk — Component Breakdown", "Score")
    ax.legend(fontsize=6, loc="lower right", ncol=2)

    # =========================================================================
    # 4. FA Score vs Distance to Default scatter (mid-center)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1])
    for n in names_data:
        if n["alert"] == "HIGH RISK":
            c, marker = COLORS["red"], "^"
        elif n["alert"] == "WATCH LIST":
            c, marker = COLORS["orange"], "s"
        elif n["alert"] == "RS STRONG":
            c, marker = COLORS["green"], "D"
        else:
            c, marker = COLORS["text_dim"], "o"
        ax.scatter(n["dd"], n["fa_score"], color=c, marker=marker,
                   s=35, alpha=0.7, edgecolors="white", linewidth=0.3)
        if n["fa_score"] > 55 or n["rs_score"] > 55:
            ax.annotate(n["name"][:10], (n["dd"], n["fa_score"]),
                        fontsize=5, color=COLORS["text_dim"],
                        textcoords="offset points", xytext=(4, 4))

    ax.axhline(y=60, color=COLORS["red"], linestyle="--", linewidth=0.7,
               label="FA High Risk")
    ax.axhline(y=40, color=COLORS["orange"], linestyle="--", linewidth=0.5,
               label="FA Watch")
    style_ax(ax, "FA Score vs Distance to Default",
             "Distance to Default", "FA Score")
    ax.legend(fontsize=6)

    # =========================================================================
    # 5. Sector FA Risk Map (mid-right)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 2])
    sector_risk = {}
    for n in names_data:
        s = n["sector"]
        if s not in sector_risk:
            sector_risk[s] = []
        sector_risk[s].append(n["fa_score"])

    sorted_sectors = sorted(sector_risk.items(),
                            key=lambda x: np.mean(x[1]), reverse=True)
    s_names = [s[0] for s in sorted_sectors]
    s_avgs = [np.mean(s[1]) for s in sorted_sectors]
    s_colors = [COLORS["red"] if v > 45 else COLORS["orange"] if v > 35
                else COLORS["green"] for v in s_avgs]

    ax.barh(s_names, s_avgs, color=s_colors, alpha=0.85)
    ax.axvline(x=45, color=COLORS["red"], linestyle="--", linewidth=0.5,
               label="High Risk")
    ax.axvline(x=35, color=COLORS["orange"], linestyle="--", linewidth=0.5,
               label="Watch")
    for i, v in enumerate(s_avgs):
        ax.text(v + 0.5, i, f"{v:.1f}", va="center", fontsize=7,
                color=COLORS["text"])
    style_ax(ax, "Sector FA Risk Map", "Avg FA Score")
    ax.tick_params(axis="y", labelsize=7)
    ax.legend(fontsize=6)

    # =========================================================================
    # 6. Alert Table (bottom, full width)
    # =========================================================================
    ax = fig.add_subplot(gs[2, :])
    ax.axis("off")

    # Show top FA risk and RS candidates
    alert_names = [n for n in names_data if n["alert"] in
                   ("HIGH RISK", "WATCH LIST", "RS STRONG")]
    alert_names.sort(key=lambda x: (
        0 if x["alert"] == "HIGH RISK" else
        1 if x["alert"] == "WATCH LIST" else 2,
        -x["fa_score"]
    ))

    col_labels = ["Name", "Rating", "Sector", "DD", "FA Score",
                  "RS Score", "Alert"]
    table_data = []
    for n in alert_names[:25]:
        table_data.append([
            n["name"], n["rating"], n["sector"],
            f"{n['dd']:.1f}", f"{n['fa_score']:.1f}",
            f"{n['rs_score']:.1f}", n["alert"],
        ])

    if not table_data:
        table_data = [["—"] * 7]

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
            if key[1] == 6:  # Alert column
                text = cell.get_text().get_text()
                if text == "HIGH RISK":
                    cell.set_text_props(color=COLORS["red"], fontweight="bold")
                elif text == "WATCH LIST":
                    cell.set_text_props(color=COLORS["orange"])
                elif text == "RS STRONG":
                    cell.set_text_props(color=COLORS["green"], fontweight="bold")

    style_ax(ax, "Fallen Angel / Rising Star — Alert Table")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Fallen Angel / Rising Star Screener</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Fallen Angel Charts">
</body></html>
"""


@fallen_angels_bp.route("/fallen-angels")
def fallen_angels():
    chart = generate_fallen_angel_charts()
    return render_template_string(TEMPLATE, chart=chart)
