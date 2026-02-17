"""
Dispersion & Correlation Monitor
Route: /dispersion

Tracks implied vs realized correlation, spread dispersion,
equity correlation heatmaps, and sector-level dispersion analysis.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

dispersion_bp = Blueprint("dispersion_monitor", __name__)

N_DAYS = 252
SECTORS = ["Autos", "Banks", "Basic Res", "Chemicals", "Cons Goods",
           "Energy", "Healthcare", "Industrials", "Insurance", "Media",
           "Real Estate", "Tech", "Telecom", "Travel", "Utilities"]


def _generate_dispersion_data():
    """Generate synthetic correlation and dispersion data."""
    np.random.seed(456)
    t = np.arange(N_DAYS)

    implied_corr = 0.55 + 0.15 * np.sin(t / 30) + np.random.normal(0, 0.03, N_DAYS)
    realized_corr = implied_corr - 0.08 + np.random.normal(0, 0.05, N_DAYS)
    implied_corr = np.clip(implied_corr, 0.2, 0.9)
    realized_corr = np.clip(realized_corr, 0.1, 0.85)

    corr_premium = implied_corr - realized_corr

    # Spread dispersion by sector
    sector_disp = {}
    for s in SECTORS:
        base = 30 + np.random.random() * 50
        sector_disp[s] = base + 15 * np.sin(t / (20 + np.random.random() * 30)) \
                         + np.random.normal(0, 5, N_DAYS)
        sector_disp[s] = np.clip(sector_disp[s], 5, 150)

    # Equity correlation matrix
    n_eq = 12
    eq_names = ["SX5E", "DAX", "CAC", "FTSE", "SPX", "NDX", "NKY",
                "HSI", "KOSPI", "ASX", "TSX", "IBOV"]
    base_corr = np.random.uniform(0.3, 0.8, (n_eq, n_eq))
    eq_corr = (base_corr + base_corr.T) / 2
    np.fill_diagonal(eq_corr, 1.0)

    # Top dispersed names
    top_names = [
        ("Ardagh", 820, 45), ("Casino Guichard", 1250, 62),
        ("Altice France", 980, 55), ("Intrum", 650, 38),
        ("Teva Pharma", 420, 28), ("Telecom Italia", 380, 25),
        ("Bayer", 350, 22), ("Grifols", 310, 20),
        ("Atos", 1500, 70), ("SFR", 720, 40),
    ]

    # Composite signal
    avg_disp = np.mean([sector_disp[s] for s in SECTORS], axis=0)
    z_corr = (corr_premium - np.mean(corr_premium)) / np.std(corr_premium)
    z_disp = (avg_disp - np.mean(avg_disp)) / np.std(avg_disp)
    composite = 0.5 * z_corr + 0.5 * z_disp

    return {
        "implied_corr": implied_corr, "realized_corr": realized_corr,
        "corr_premium": corr_premium, "sector_disp": sector_disp,
        "eq_corr": eq_corr, "eq_names": eq_names,
        "top_names": top_names, "composite": composite,
    }


def generate_dispersion_charts():
    """Generate all dispersion & correlation charts."""
    setup_dark_style()
    data = _generate_dispersion_data()
    t = np.arange(N_DAYS)

    fig = plt.figure(figsize=(22, 16), facecolor=COLORS["bg"])
    fig.suptitle("DISPERSION & CORRELATION MONITOR",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35,
                          top=0.93, bottom=0.06, left=0.06, right=0.97)

    # 1. Implied vs Realized Correlation
    ax = fig.add_subplot(gs[0, 0])
    ax.plot(t, data["implied_corr"], color=COLORS["cyan"], linewidth=1.5,
            label="Implied")
    ax.plot(t, data["realized_corr"], color=COLORS["orange"], linewidth=1.5,
            label="Realized")
    ax.fill_between(t, data["implied_corr"], data["realized_corr"],
                    alpha=0.2, color=COLORS["purple"], label="Premium")
    style_ax(ax, "Implied vs Realized Correlation", "Days", "Correlation")
    ax.legend(fontsize=7)

    # 2. Composite Dispersion Signal
    ax = fig.add_subplot(gs[0, 1])
    comp = data["composite"]
    ax.plot(t, comp, color=COLORS["purple"], linewidth=1.5)
    ax.fill_between(t, comp, where=comp > 0, alpha=0.2, color=COLORS["green"])
    ax.fill_between(t, comp, where=comp < 0, alpha=0.2, color=COLORS["red"])
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.axhline(y=1.5, color=COLORS["yellow"], linestyle="--", linewidth=0.7,
               label="High Disp")
    ax.axhline(y=-1.5, color=COLORS["yellow"], linestyle="--", linewidth=0.7)
    style_ax(ax, "Composite Dispersion Signal", "Days", "Z-Score")
    ax.legend(fontsize=7)

    # 3. Signal Components (stacked area)
    ax = fig.add_subplot(gs[0, 2])
    corr_comp = data["corr_premium"]
    avg_disp = np.mean([data["sector_disp"][s] for s in SECTORS], axis=0)
    z_c = (corr_comp - np.mean(corr_comp)) / np.std(corr_comp)
    z_d = (avg_disp - np.mean(avg_disp)) / np.std(avg_disp)
    ax.plot(t, z_c, color=COLORS["cyan"], linewidth=1.2, label="Corr Premium (z)")
    ax.plot(t, z_d, color=COLORS["orange"], linewidth=1.2, label="Spread Disp (z)")
    ax.fill_between(t, z_c, alpha=0.1, color=COLORS["cyan"])
    ax.fill_between(t, z_d, alpha=0.1, color=COLORS["orange"])
    style_ax(ax, "Signal Components", "Days", "Z-Score")
    ax.legend(fontsize=7)

    # 4. Spread Dispersion by Sector (latest)
    ax = fig.add_subplot(gs[1, 0])
    latest_disp = {s: data["sector_disp"][s][-1] for s in SECTORS}
    sorted_sectors = sorted(latest_disp.items(), key=lambda x: x[1], reverse=True)
    names = [s[0] for s in sorted_sectors]
    vals = [s[1] for s in sorted_sectors]
    colors = [COLORS["red"] if v > 60 else COLORS["orange"] if v > 40
              else COLORS["green"] for v in vals]
    ax.barh(names, vals, color=colors, alpha=0.85)
    ax.axvline(x=60, color=COLORS["red"], linestyle="--", linewidth=0.7, label="High")
    style_ax(ax, "Sector Spread Dispersion (Latest)", "Dispersion (bps)")
    ax.tick_params(axis="y", labelsize=7)
    ax.legend(fontsize=7)

    # 5. Equity Correlation Heatmap
    ax = fig.add_subplot(gs[1, 1])
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "apex", [COLORS["blue"], COLORS["panel"], COLORS["red"]])
    im = ax.imshow(data["eq_corr"], cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(data["eq_names"])))
    ax.set_yticks(range(len(data["eq_names"])))
    ax.set_xticklabels(data["eq_names"], rotation=45, ha="right", fontsize=6)
    ax.set_yticklabels(data["eq_names"], fontsize=6)
    for i in range(len(data["eq_names"])):
        for j in range(len(data["eq_names"])):
            val = data["eq_corr"][i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=5, color="white" if val > 0.6 else COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.8)
    style_ax(ax, "Equity Correlation Heatmap")

    # 6. Sector spread dispersion time series (top 5)
    ax = fig.add_subplot(gs[1, 2])
    top5 = sorted(SECTORS, key=lambda s: data["sector_disp"][s][-1], reverse=True)[:5]
    for i, s in enumerate(top5):
        ax.plot(t, data["sector_disp"][s], color=PALETTE[i], linewidth=1.2, label=s)
    style_ax(ax, "Top 5 Sector Dispersion (Time Series)", "Days", "Dispersion (bps)")
    ax.legend(fontsize=7, loc="upper left")

    # 7. Top Dispersed Names table
    ax = fig.add_subplot(gs[2, :])
    ax.axis("off")
    col_labels = ["Name", "CDS Spread (bps)", "30d Move (bps)", "Signal"]
    table_data = []
    for name, spread, move in data["top_names"]:
        signal = "WIDEN" if move > 30 else "TIGHT" if move < -10 else "NEUTRAL"
        table_data.append([name, f"{spread}", f"+{move}" if move > 0 else f"{move}", signal])

    table = ax.table(cellText=table_data, colLabels=col_labels,
                     cellLoc="center", loc="center",
                     colColours=[COLORS["panel"]] * 4)
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)

    for key, cell in table.get_celld().items():
        cell.set_edgecolor(COLORS["grid"])
        if key[0] == 0:  # Header
            cell.set_facecolor(COLORS["purple"])
            cell.set_text_props(color="white", fontweight="bold")
        else:
            cell.set_facecolor(COLORS["panel"])
            cell.set_text_props(color=COLORS["text"])
            # Color code signal column
            if key[1] == 3:
                text = cell.get_text().get_text()
                if text == "WIDEN":
                    cell.set_text_props(color=COLORS["red"])
                elif text == "TIGHT":
                    cell.set_text_props(color=COLORS["green"])

    style_ax(ax, "Top Dispersed Names — iTraxx / Crossover Universe")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Dispersion & Correlation Monitor</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1600px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Dispersion Charts">
</body></html>
"""


@dispersion_bp.route("/dispersion")
def dispersion():
    chart = generate_dispersion_charts()
    return render_template_string(TEMPLATE, chart=chart)
