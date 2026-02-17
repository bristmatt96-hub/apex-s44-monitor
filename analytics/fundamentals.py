"""
Fundamental Credit Analysis — iTraxx Crossover Universe
Route: /fundamentals

Gross leverage (Debt/EBITDA) for 61 names, coverage vs leverage scatter,
sector credit quality heatmap, FCF/Debt repayment capacity, margin vs growth
scatter, and credit universe summary.
"""

import numpy as np
from datetime import datetime
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

fundamentals_bp = Blueprint("fundamentals", __name__)

# ---------------------------------------------------------------------------
# iTraxx Crossover universe — 61 names with fundamentals
# ---------------------------------------------------------------------------
NAMES = [
    {"name": "Ardagh", "sector": "Packaging", "rating": "CCC+"},
    {"name": "Casino Guichard", "sector": "Retail", "rating": "CCC"},
    {"name": "Altice France", "sector": "Telecom", "rating": "CCC+"},
    {"name": "Intrum", "sector": "Financial Svcs", "rating": "B-"},
    {"name": "Atos", "sector": "Technology", "rating": "CC"},
    {"name": "SFR", "sector": "Telecom", "rating": "B"},
    {"name": "Teva Pharma", "sector": "Healthcare", "rating": "BB-"},
    {"name": "Grifols", "sector": "Healthcare", "rating": "BB"},
    {"name": "Telecom Italia", "sector": "Telecom", "rating": "BB-"},
    {"name": "Bayer", "sector": "Chemicals", "rating": "BBB-"},
    {"name": "Loxam", "sector": "Industrials", "rating": "BB"},
    {"name": "Stonegate", "sector": "Travel & Leisure", "rating": "B"},
    {"name": "Verisure", "sector": "Industrials", "rating": "BB-"},
    {"name": "Picard", "sector": "Food & Bev", "rating": "B"},
    {"name": "Maxeda", "sector": "Retail", "rating": "B-"},
    {"name": "Renault", "sector": "Autos", "rating": "BBB-"},
    {"name": "Peugeot", "sector": "Autos", "rating": "BBB"},
    {"name": "Vodafone", "sector": "Telecom", "rating": "BBB"},
    {"name": "Nokia", "sector": "Technology", "rating": "BBB-"},
    {"name": "Lufthansa", "sector": "Travel & Leisure", "rating": "BBB-"},
    {"name": "Rolls-Royce", "sector": "Industrials", "rating": "BB+"},
    {"name": "ThyssenKrupp", "sector": "Basic Resources", "rating": "BB-"},
    {"name": "ArcelorMittal", "sector": "Basic Resources", "rating": "BBB-"},
    {"name": "HeidelbergCement", "sector": "Construction", "rating": "BBB-"},
    {"name": "Repsol", "sector": "Energy", "rating": "BBB"},
    {"name": "EDP", "sector": "Utilities", "rating": "BBB"},
    {"name": "Enel", "sector": "Utilities", "rating": "BBB+"},
    {"name": "Unibail", "sector": "Real Estate", "rating": "BBB+"},
    {"name": "ING Group", "sector": "Banks", "rating": "A-"},
    {"name": "Commerzbank", "sector": "Banks", "rating": "BBB+"},
    {"name": "Aegon", "sector": "Insurance", "rating": "BBB"},
    {"name": "Adecco", "sector": "Industrials", "rating": "BBB"},
    {"name": "Marks & Spencer", "sector": "Retail", "rating": "BB+"},
    {"name": "Carrefour", "sector": "Retail", "rating": "BBB"},
    {"name": "Vivendi", "sector": "Media", "rating": "BBB-"},
    {"name": "ProSiebenSat.1", "sector": "Media", "rating": "BB+"},
    {"name": "TUI", "sector": "Travel & Leisure", "rating": "B+"},
    {"name": "IAG", "sector": "Travel & Leisure", "rating": "BBB-"},
    {"name": "Leonardo", "sector": "Industrials", "rating": "BBB-"},
    {"name": "Continental", "sector": "Autos", "rating": "BBB"},
    {"name": "Pernod Ricard", "sector": "Food & Bev", "rating": "BBB+"},
    {"name": "Danone", "sector": "Food & Bev", "rating": "BBB+"},
    {"name": "Accor", "sector": "Travel & Leisure", "rating": "BBB-"},
    {"name": "Faurecia", "sector": "Autos", "rating": "BB+"},
    {"name": "ZF Friedrichshafn", "sector": "Autos", "rating": "BB+"},
    {"name": "Samsonite", "sector": "Consumer Goods", "rating": "BB+"},
    {"name": "Ineos", "sector": "Chemicals", "rating": "BB"},
    {"name": "Techem", "sector": "Industrials", "rating": "BB-"},
    {"name": "OI Glass", "sector": "Packaging", "rating": "BB-"},
    {"name": "Selecta", "sector": "Food & Bev", "rating": "B-"},
    {"name": "Cirsa", "sector": "Travel & Leisure", "rating": "B+"},
    {"name": "Eircom", "sector": "Telecom", "rating": "BB-"},
    {"name": "Wind Tre", "sector": "Telecom", "rating": "B+"},
    {"name": "Maisons du Monde", "sector": "Retail", "rating": "B"},
    {"name": "Douglas", "sector": "Retail", "rating": "B"},
    {"name": "CBR Fashion", "sector": "Consumer Goods", "rating": "B-"},
    {"name": "Birkenstock", "sector": "Consumer Goods", "rating": "BB"},
    {"name": "Tereos", "sector": "Food & Bev", "rating": "BB-"},
    {"name": "Europcar", "sector": "Travel & Leisure", "rating": "B+"},
    {"name": "Puma Energy", "sector": "Energy", "rating": "BB-"},
    {"name": "Ceconomy", "sector": "Retail", "rating": "BB"},
]


def _rating_order(r):
    """Numeric order for coloring."""
    scale = {"CC": 0, "CCC": 1, "CCC+": 2, "B-": 3, "B": 4, "B+": 5,
             "BB-": 6, "BB": 7, "BB+": 8, "BBB-": 9, "BBB": 10,
             "BBB+": 11, "A-": 12, "A": 13}
    return scale.get(r, 7)


def _generate_fundamentals():
    """Generate synthetic fundamental data for 61 names."""
    np.random.seed(850)

    data = []
    for n in NAMES:
        ro = _rating_order(n["rating"])
        # Leverage inversely correlated with rating
        leverage = max(0.5, 8.0 - ro * 0.5 + np.random.normal(0, 1.2))
        # Coverage positively correlated with rating
        coverage = max(0.5, ro * 1.5 + np.random.normal(2, 3))
        # FCF/Debt
        fcf_debt = (ro - 5) * 4 + np.random.normal(0, 10)
        # EBITDA margin
        ebitda_margin = 10 + ro * 2 + np.random.normal(0, 8)
        ebitda_margin = max(2, min(60, ebitda_margin))
        # Revenue growth (3yr CAGR)
        rev_growth = np.random.normal(3, 8)

        # Flags
        flags = []
        if coverage < 2.0:
            flags.append("LOW_COV")
        if leverage > 6.0:
            flags.append("HIGH_LEV")
        if fcf_debt < 0:
            flags.append("NEG_FCF")

        data.append({
            **n,
            "leverage": leverage, "coverage": coverage,
            "fcf_debt": fcf_debt, "ebitda_margin": ebitda_margin,
            "rev_growth": rev_growth, "flags": flags,
            "rating_num": ro,
        })

    # Sort by leverage for the main bar chart
    data.sort(key=lambda x: x["leverage"], reverse=True)

    flagged = sum(1 for d in data if d["flags"])
    low_cov = sum(1 for d in data if "LOW_COV" in d["flags"])
    high_lev = sum(1 for d in data if "HIGH_LEV" in d["flags"])
    neg_fcf = sum(1 for d in data if "NEG_FCF" in d["flags"])

    return {
        "names_data": data,
        "flagged": flagged, "low_cov": low_cov,
        "high_lev": high_lev, "neg_fcf": neg_fcf,
    }


def generate_fundamentals_charts():
    """Generate fundamental credit analysis charts."""
    setup_dark_style()
    data = _generate_fundamentals()

    fig = plt.figure(figsize=(26, 20), facecolor=COLORS["bg"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.suptitle("FUNDAMENTAL CREDIT ANALYSIS — iTRAXX CROSSOVER UNIVERSE",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)
    fig.text(0.5, 0.955,
             f"Generated: {now} | {len(data['names_data'])} names with fundamentals",
             ha="center", fontsize=10, color=COLORS["text_dim"])

    gs = fig.add_gridspec(3, 3, hspace=0.4, wspace=0.35,
                          top=0.93, bottom=0.03, left=0.08, right=0.97)

    names_data = data["names_data"]

    # =========================================================================
    # 1. Gross Leverage (Debt/EBITDA) — full height left column
    # =========================================================================
    ax = fig.add_subplot(gs[:2, 0])
    names = [d["name"] for d in names_data]
    levs = [d["leverage"] for d in names_data]
    lev_colors = []
    for lev in levs:
        if lev > 6.0:
            lev_colors.append(COLORS["red"])
        elif lev > 4.0:
            lev_colors.append(COLORS["orange"])
        elif lev > 2.5:
            lev_colors.append(COLORS["yellow"])
        else:
            lev_colors.append(COLORS["green"])

    ax.barh(names, levs, color=lev_colors, alpha=0.85, height=0.7)
    ax.axvline(x=2.5, color=COLORS["green"], linestyle="--", linewidth=0.7,
               label="2.5x IG")
    ax.axvline(x=4.0, color=COLORS["yellow"], linestyle="--", linewidth=0.7,
               label="4.0x BB")
    ax.axvline(x=6.0, color=COLORS["red"], linestyle="--", linewidth=0.7,
               label="6.0x High")
    style_ax(ax, "Gross Leverage (Debt/EBITDA)", "Leverage (x)")
    ax.tick_params(axis="y", labelsize=5)
    ax.legend(fontsize=6, loc="lower right")

    # =========================================================================
    # 2. Credit Universe Summary (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")

    leverages = [d["leverage"] for d in names_data]
    coverages = [d["coverage"] for d in names_data]
    fcfs = [d["fcf_debt"] for d in names_data]

    summary = (
        f"CREDIT UNIVERSE SUMMARY\n"
        f"{'─' * 30}\n"
        f"Names:         {len(names_data)}\n"
        f"Flagged:       {data['flagged']}\n"
        f"{'─' * 30}\n"
        f"Avg Leverage:  {np.mean(leverages):.1f}x\n"
        f"Median Leverage:{np.median(leverages):.1f}x\n"
        f"Avg Coverage:  {np.mean(coverages):.1f}x\n"
        f"Avg FCF/Debt:  {np.mean(fcfs):+.1f}%\n"
        f"{'─' * 30}\n"
        f"LOW_COV:       {data['low_cov']}\n"
        f"HIGH_LEV:      {data['high_lev']}\n"
        f"NEG_FCF:       {data['neg_fcf']}\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=COLORS["orange"], linewidth=2))
    style_ax(ax, "Credit Universe Summary")

    # =========================================================================
    # 3. Coverage vs Leverage scatter (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    for d in names_data:
        c = COLORS["red"] if d["leverage"] > 6 else \
            COLORS["orange"] if d["leverage"] > 4 else \
            COLORS["green"]
        ax.scatter(d["leverage"], d["coverage"], color=c, alpha=0.6,
                   s=30, edgecolors="white", linewidth=0.3)
        if d["leverage"] > 7 or d["coverage"] < 2:
            ax.annotate(d["name"][:8], (d["leverage"], d["coverage"]),
                        fontsize=5, color=COLORS["text_dim"],
                        textcoords="offset points", xytext=(3, 3))

    ax.axvline(x=2.5, color=COLORS["green"], linestyle="--", linewidth=0.5)
    ax.axvline(x=4.0, color=COLORS["yellow"], linestyle="--", linewidth=0.5)
    ax.axvline(x=6.0, color=COLORS["red"], linestyle="--", linewidth=0.5)
    ax.axhline(y=2.0, color=COLORS["red"], linestyle="--", linewidth=0.5,
               label="Min Coverage")
    style_ax(ax, "Coverage vs Leverage",
             "Gross Leverage (Debt/EBITDA)", "Interest Coverage (EBITDA/Int)")
    ax.legend(fontsize=6)

    # =========================================================================
    # 4. Sector Credit Quality Heatmap (mid-center+right)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1:])
    sector_agg = {}
    for d in names_data:
        s = d["sector"]
        if s not in sector_agg:
            sector_agg[s] = {"lev": [], "cov": [], "margin": [], "growth": []}
        sector_agg[s]["lev"].append(d["leverage"])
        sector_agg[s]["cov"].append(d["coverage"])
        sector_agg[s]["margin"].append(d["ebitda_margin"])
        sector_agg[s]["growth"].append(d["rev_growth"])

    sector_list = sorted(sector_agg.keys())
    metrics = ["Leverage", "Coverage", "EBITDA Margin", "Revenue Growth"]
    heat = np.zeros((len(sector_list), 4))

    for i, s in enumerate(sector_list):
        # Normalize: green = good. For leverage, lower is better (invert)
        lev_avg = np.mean(sector_agg[s]["lev"])
        heat[i, 0] = 1.0 - min(lev_avg / 8.0, 1.0)  # Inverted
        heat[i, 1] = min(np.mean(sector_agg[s]["cov"]) / 15.0, 1.0)
        heat[i, 2] = min(np.mean(sector_agg[s]["margin"]) / 40.0, 1.0)
        heat[i, 3] = (np.mean(sector_agg[s]["growth"]) + 10) / 30.0

    heat = np.clip(heat, 0, 1)
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "quality", [COLORS["red"], COLORS["yellow"], COLORS["green"]])
    im = ax.imshow(heat, cmap=cmap, aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(4))
    ax.set_yticks(range(len(sector_list)))
    ax.set_xticklabels(metrics, fontsize=8, rotation=20, ha="right")
    ax.set_yticklabels(sector_list, fontsize=7)

    # Raw values as text
    for i, s in enumerate(sector_list):
        raw = [np.mean(sector_agg[s]["lev"]),
               np.mean(sector_agg[s]["cov"]),
               np.mean(sector_agg[s]["margin"]),
               np.mean(sector_agg[s]["growth"])]
        fmts = [f"{raw[0]:.1f}x", f"{raw[1]:.1f}x",
                f"{raw[2]:.0f}%", f"{raw[3]:+.1f}%"]
        for j in range(4):
            ax.text(j, i, fmts[j], ha="center", va="center", fontsize=6,
                    color="white" if heat[i, j] < 0.4 or heat[i, j] > 0.7
                    else COLORS["text"])

    fig.colorbar(im, ax=ax, shrink=0.6, label="Quality →")
    style_ax(ax, "Sector Credit Quality Heatmap (green=better)")

    # =========================================================================
    # 5. FCF / Debt — Repayment Capacity (bottom-left)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 0])
    sorted_fcf = sorted(names_data, key=lambda x: x["fcf_debt"])
    # Show top/bottom 20
    show = sorted_fcf[:10] + sorted_fcf[-10:]
    f_names = [d["name"] for d in show]
    f_vals = [d["fcf_debt"] for d in show]
    f_colors = [COLORS["green"] if v > 0 else COLORS["red"] for v in f_vals]
    ax.barh(f_names, f_vals, color=f_colors, alpha=0.85)
    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.8)
    style_ax(ax, "FCF / Debt (%) — Repayment Capacity", "FCF/Debt (%)")
    ax.tick_params(axis="y", labelsize=5)

    # =========================================================================
    # 6. Margin vs Growth scatter (bottom-center+right)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 1:])
    rating_cmap = mcolors.LinearSegmentedColormap.from_list(
        "rating", [COLORS["red"], COLORS["orange"], COLORS["yellow"], COLORS["green"]])

    for d in names_data:
        norm_r = d["rating_num"] / 13.0
        c = rating_cmap(norm_r)
        ax.scatter(d["rev_growth"], d["ebitda_margin"], color=c, alpha=0.7,
                   s=40, edgecolors="white", linewidth=0.3)
        if d["ebitda_margin"] > 40 or d["rev_growth"] > 15 or d["rev_growth"] < -10:
            ax.annotate(d["name"][:10], (d["rev_growth"], d["ebitda_margin"]),
                        fontsize=5, color=COLORS["text_dim"],
                        textcoords="offset points", xytext=(3, 3))

    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.axhline(y=15, color=COLORS["text_dim"], linewidth=0.5, linestyle="--")

    # Rating legend
    from matplotlib.lines import Line2D
    rating_labels = ["CCC/CC", "B", "BB", "BBB+"]
    rating_vals = [0.1, 0.35, 0.6, 0.9]
    handles = [Line2D([0], [0], marker="o", color="w",
                      markerfacecolor=rating_cmap(v), markersize=6, label=l)
               for v, l in zip(rating_vals, rating_labels)]
    ax.legend(handles=handles, fontsize=7, loc="upper right", title="Rating",
              title_fontsize=7)
    style_ax(ax, "Margin vs Growth (color=rating)",
             "Revenue CAGR 3yr (%)", "EBITDA Margin (%)")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Fundamental Credit Analysis</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Fundamentals Charts">
</body></html>
"""


@fundamentals_bp.route("/fundamentals")
def fundamentals():
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("fundamentals", generate_fundamentals_charts)
    return render_template_string(TEMPLATE, chart=chart)
