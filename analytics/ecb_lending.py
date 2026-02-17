"""
ECB Lending Conditions Monitor
Route: /ecb-lending

Monitors Bank Lending Survey (BLS), NFC loan growth by country,
sector production indicators, and country lending conditions heatmap.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

ecb_bp = Blueprint("ecb_lending", __name__)

# ---------------------------------------------------------------------------
# ECB data definitions
# ---------------------------------------------------------------------------
COUNTRIES = ["Germany", "France", "Italy", "Spain", "Netherlands",
             "Belgium", "Austria", "Portugal", "Ireland", "Greece"]

QUARTERS = ["Q1'23", "Q2'23", "Q3'23", "Q4'23",
            "Q1'24", "Q2'24", "Q3'24", "Q4'24",
            "Q1'25", "Q2'25", "Q3'25", "Q4'25"]

SECTORS = ["Manufacturing", "Construction", "Services", "Energy",
           "Transport", "Real Estate", "Tech/Digital", "Agriculture"]


def _generate_ecb_data():
    """Generate synthetic ECB lending data."""
    np.random.seed(789)
    n_q = len(QUARTERS)

    # BLS net tightening (% of banks tightening - % easing)
    bls_enterprise = 15 - 20 * np.linspace(0, 1, n_q) + np.random.normal(0, 3, n_q)
    bls_consumer = 10 - 15 * np.linspace(0, 1, n_q) + np.random.normal(0, 4, n_q)
    bls_mortgage = 8 - 12 * np.linspace(0, 1, n_q) + np.random.normal(0, 3, n_q)

    # Composite lending Z-score
    composite_z = -0.5 + 1.5 * np.linspace(0, 1, n_q) + np.random.normal(0, 0.3, n_q)

    # NFC loan growth by country (% YoY)
    nfc_growth = {}
    for c in COUNTRIES:
        base = np.random.uniform(-2, 3)
        trend = np.random.uniform(0.1, 0.4)
        nfc_growth[c] = base + trend * np.arange(n_q) + np.random.normal(0, 0.5, n_q)

    # Sector production indicators (PMI-style, 50=neutral)
    sector_pmi = {}
    for s in SECTORS:
        base = np.random.uniform(45, 55)
        sector_pmi[s] = base + 3 * np.sin(np.arange(n_q) / 3) + np.random.normal(0, 1.5, n_q)

    # Country lending conditions heatmap
    # Dimensions: Credit Standards, Demand, Terms, Risk Perception
    conditions_dims = ["Credit\nStandards", "Loan\nDemand", "Terms &\nConditions",
                       "Risk\nPerception"]
    conditions = np.random.uniform(-1, 1, (len(COUNTRIES), len(conditions_dims)))
    # Make it somewhat realistic
    conditions[:, 0] = np.random.uniform(-0.5, 0.8, len(COUNTRIES))  # Standards tightening
    conditions[:, 1] = np.random.uniform(-0.8, 0.3, len(COUNTRIES))  # Demand weak
    conditions[:, 2] = np.random.uniform(-0.3, 0.6, len(COUNTRIES))  # Terms tightening
    conditions[:, 3] = np.random.uniform(0, 0.9, len(COUNTRIES))  # Risk elevated

    return {
        "bls_enterprise": bls_enterprise, "bls_consumer": bls_consumer,
        "bls_mortgage": bls_mortgage, "composite_z": composite_z,
        "nfc_growth": nfc_growth, "sector_pmi": sector_pmi,
        "conditions": conditions, "conditions_dims": conditions_dims,
    }


def generate_ecb_charts():
    """Generate ECB lending conditions charts."""
    setup_dark_style()
    data = _generate_ecb_data()

    fig = plt.figure(figsize=(22, 16), facecolor=COLORS["bg"])
    fig.suptitle("ECB LENDING CONDITIONS MONITOR",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(3, 3, hspace=0.5, wspace=0.35,
                          top=0.93, bottom=0.06, left=0.06, right=0.97)

    # 1. Lending Composite Z-Score
    ax = fig.add_subplot(gs[0, 0])
    z = data["composite_z"]
    ax.plot(QUARTERS, z, "o-", color=COLORS["cyan"], linewidth=2, markersize=6)
    ax.fill_between(range(len(QUARTERS)), z, where=z > 0,
                    alpha=0.2, color=COLORS["green"])
    ax.fill_between(range(len(QUARTERS)), z, where=z < 0,
                    alpha=0.2, color=COLORS["red"])
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.8)
    ax.axhline(y=1, color=COLORS["green"], linestyle="--", linewidth=0.5, label="Easing")
    ax.axhline(y=-1, color=COLORS["red"], linestyle="--", linewidth=0.5, label="Tightening")
    ax.set_xticks(range(len(QUARTERS)))
    ax.set_xticklabels(QUARTERS, rotation=45, ha="right", fontsize=7)
    style_ax(ax, "Lending Composite Z-Score", ylabel="Z-Score")
    ax.legend(fontsize=7)

    # 2. BLS Enterprise Survey
    ax = fig.add_subplot(gs[0, 1])
    x = range(len(QUARTERS))
    ax.plot(x, data["bls_enterprise"], "o-", color=COLORS["cyan"],
            linewidth=1.5, label="Enterprise", markersize=4)
    ax.plot(x, data["bls_consumer"], "s-", color=COLORS["orange"],
            linewidth=1.5, label="Consumer", markersize=4)
    ax.plot(x, data["bls_mortgage"], "^-", color=COLORS["purple"],
            linewidth=1.5, label="Mortgage", markersize=4)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.8)
    ax.fill_between(x, data["bls_enterprise"], 0,
                    where=np.array(data["bls_enterprise"]) > 0,
                    alpha=0.1, color=COLORS["red"])
    ax.set_xticks(x)
    ax.set_xticklabels(QUARTERS, rotation=45, ha="right", fontsize=7)
    style_ax(ax, "BLS Net Tightening (%)", ylabel="Net % Tightening")
    ax.legend(fontsize=7)

    # 3. NFC Loan Growth by Country (latest 4 quarters)
    ax = fig.add_subplot(gs[0, 2])
    latest_growth = {c: data["nfc_growth"][c][-1] for c in COUNTRIES}
    sorted_countries = sorted(latest_growth.items(), key=lambda x: x[1])
    c_names = [c[0] for c in sorted_countries]
    c_vals = [c[1] for c in sorted_countries]
    colors = [COLORS["green"] if v > 0 else COLORS["red"] for v in c_vals]
    ax.barh(c_names, c_vals, color=colors, alpha=0.85)
    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.8)
    for i, v in enumerate(c_vals):
        ax.text(v + 0.1 if v > 0 else v - 0.1, i,
                f"{v:.1f}%", va="center", fontsize=7,
                ha="left" if v > 0 else "right", color=COLORS["text"])
    style_ax(ax, "NFC Loan Growth (% YoY, Latest)", "Growth (%)")
    ax.tick_params(axis="y", labelsize=8)

    # 4. NFC Loan Growth time series (top 5 countries)
    ax = fig.add_subplot(gs[1, 0])
    top5 = sorted(COUNTRIES, key=lambda c: data["nfc_growth"][c][-1], reverse=True)[:5]
    for i, c in enumerate(top5):
        ax.plot(range(len(QUARTERS)), data["nfc_growth"][c],
                color=PALETTE[i], linewidth=1.5, label=c, marker="o", markersize=3)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(range(len(QUARTERS)))
    ax.set_xticklabels(QUARTERS, rotation=45, ha="right", fontsize=7)
    style_ax(ax, "NFC Loan Growth — Top 5 Countries", ylabel="Growth (% YoY)")
    ax.legend(fontsize=7, loc="lower right")

    # 5. Sector Production Indicators
    ax = fig.add_subplot(gs[1, 1])
    latest_pmi = {s: data["sector_pmi"][s][-1] for s in SECTORS}
    sorted_sectors = sorted(latest_pmi.items(), key=lambda x: x[1])
    s_names = [s[0] for s in sorted_sectors]
    s_vals = [s[1] for s in sorted_sectors]
    colors = [COLORS["green"] if v > 50 else COLORS["red"] for v in s_vals]
    bars = ax.barh(s_names, s_vals, color=colors, alpha=0.85)
    ax.axvline(x=50, color=COLORS["yellow"], linewidth=1.5, linestyle="--",
               label="Neutral (50)")
    for bar, val in zip(bars, s_vals):
        ax.text(val + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", va="center", fontsize=7, color=COLORS["text"])
    style_ax(ax, "Sector Production Indicators (PMI)", "PMI Level")
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(fontsize=7)

    # 6. Sector PMI time series
    ax = fig.add_subplot(gs[1, 2])
    for i, s in enumerate(SECTORS[:6]):
        ax.plot(range(len(QUARTERS)), data["sector_pmi"][s],
                color=PALETTE[i], linewidth=1.2, label=s)
    ax.axhline(y=50, color=COLORS["yellow"], linewidth=1, linestyle="--")
    ax.set_xticks(range(len(QUARTERS)))
    ax.set_xticklabels(QUARTERS, rotation=45, ha="right", fontsize=7)
    style_ax(ax, "Sector PMI Time Series", ylabel="PMI")
    ax.legend(fontsize=6, loc="lower right", ncol=2)

    # 7. Country Lending Conditions Heatmap
    ax = fig.add_subplot(gs[2, :2])
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "lending", [COLORS["green"], COLORS["yellow"], COLORS["red"]])
    # Normalize conditions to 0-1 for display
    cond_norm = (data["conditions"] - data["conditions"].min()) / \
                (data["conditions"].max() - data["conditions"].min() + 1e-8)
    im = ax.imshow(cond_norm, cmap=cmap, aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(data["conditions_dims"])))
    ax.set_yticks(range(len(COUNTRIES)))
    ax.set_xticklabels(data["conditions_dims"], fontsize=8)
    ax.set_yticklabels(COUNTRIES, fontsize=8)
    for i in range(len(COUNTRIES)):
        for j in range(len(data["conditions_dims"])):
            val = data["conditions"][i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=7,
                    color="white" if cond_norm[i, j] > 0.5 else COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.6, label="Tightening →")
    style_ax(ax, "Country Lending Conditions Heatmap (BLS Latest)")

    # 8. Summary box
    ax = fig.add_subplot(gs[2, 2])
    ax.axis("off")
    avg_tight = np.mean(data["bls_enterprise"])
    latest_z = data["composite_z"][-1]
    avg_nfc = np.mean([data["nfc_growth"][c][-1] for c in COUNTRIES])
    pmi_above_50 = sum(1 for s in SECTORS if data["sector_pmi"][s][-1] > 50)
    regime = "EASING" if latest_z > 0.5 else "TIGHTENING" if latest_z < -0.5 else "NEUTRAL"
    regime_color = COLORS["green"] if latest_z > 0.5 else \
                   COLORS["red"] if latest_z < -0.5 else COLORS["yellow"]

    summary = (
        f"ECB LENDING SUMMARY\n"
        f"{'─' * 30}\n"
        f"Regime: {regime}\n"
        f"Composite Z: {latest_z:+.2f}\n"
        f"{'─' * 30}\n"
        f"BLS Avg Tightening: {avg_tight:.1f}%\n"
        f"NFC Loan Growth: {avg_nfc:+.1f}%\n"
        f"Sectors >50 PMI: {pmi_above_50}/{len(SECTORS)}\n"
        f"{'─' * 30}\n"
        f"Strongest: Ireland\n"
        f"Weakest: Germany\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=regime_color, linewidth=1.5))
    style_ax(ax, "ECB Summary")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>ECB Lending Conditions Monitor</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1600px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="ECB Lending Charts">
</body></html>
"""


@ecb_bp.route("/ecb-lending")
def ecb_lending():
    chart = generate_ecb_charts()
    return render_template_string(TEMPLATE, chart=chart)
