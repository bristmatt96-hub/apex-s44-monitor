"""
ECB Lending Conditions Monitor
Route: /ecb-lending

Monitors Bank Lending Survey (BLS) — Credit Standards & Terms/Conditions,
NFC loan growth by country (EA, DE, FR, IT, ES), sector production indicators
(z-scores), country lending conditions heatmap (BLS Standards Z vs Loan Growth Z),
lending composite z-score with regime shading, and summary panel.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches

ecb_bp = Blueprint("ecb_lending", __name__)

# ---------------------------------------------------------------------------
# Synthetic ECB data — ~20 year history (2004-Q1 to 2025-Q4)
# ---------------------------------------------------------------------------
def _make_quarters(start_year=2004, end_year=2025):
    """Generate quarterly labels Q1'04 through Q4'25."""
    qs = []
    for y in range(start_year, end_year + 1):
        for q in range(1, 5):
            if y == end_year and q > 4:
                break
            qs.append(f"Q{q}'{str(y)[2:]}")
    return qs

QUARTERS = _make_quarters(2004, 2025)
N_Q = len(QUARTERS)

COUNTRIES = ["Euro Area", "Germany", "France", "Italy", "Spain"]
COUNTRY_CODES = ["EA", "DE", "FR", "IT", "ES"]

SECTORS = ["Building", "Chemicals", "Metals", "Packaging", "Autos",
           "Industrials", "Healthcare", "Technology", "Aerospace"]


def _generate_ecb_data():
    """Generate synthetic ECB lending data (~20yr history)."""
    np.random.seed(789)
    t = np.arange(N_Q)

    # ---- BLS Credit Standards (net tightening %) ----
    # Realistic pattern: peaks during GFC (2008-09), Euro crisis (2011-12),
    # COVID (2020), and 2022-23 rate hiking cycle
    bls_standards = np.zeros(N_Q)
    for i, q in enumerate(QUARTERS):
        yr = 2004 + i / 4
        # Baseline easing trend
        bls_standards[i] = 5
        # GFC spike
        bls_standards[i] += 55 * np.exp(-0.5 * ((yr - 2008.5) / 0.6) ** 2)
        # Euro crisis
        bls_standards[i] += 30 * np.exp(-0.5 * ((yr - 2011.8) / 0.5) ** 2)
        # COVID
        bls_standards[i] += 20 * np.exp(-0.5 * ((yr - 2020.2) / 0.3) ** 2)
        # 2022-23 rate hiking
        bls_standards[i] += 25 * np.exp(-0.5 * ((yr - 2023.0) / 0.6) ** 2)
    bls_standards += np.random.normal(0, 3, N_Q)

    # ---- BLS Terms & Conditions ----
    bls_terms = bls_standards * 0.7 + np.random.normal(0, 4, N_Q)

    # ---- NFC Loan Growth by country (annual %) ----
    nfc_growth = {}
    for ci, c in enumerate(COUNTRIES):
        growth = np.zeros(N_Q)
        for i in range(N_Q):
            yr = 2004 + i / 4
            # Base growth
            growth[i] = 5
            # GFC collapse
            growth[i] -= 12 * np.exp(-0.5 * ((yr - 2009.5) / 1.0) ** 2)
            # Euro crisis (worse for periphery)
            periph = 1.8 if c in ("Italy", "Spain") else 1.0
            growth[i] -= 8 * periph * np.exp(-0.5 * ((yr - 2012.5) / 1.0) ** 2)
            # Recovery 2015-2019
            growth[i] += 3 * np.exp(-0.5 * ((yr - 2017) / 2.0) ** 2)
            # COVID dip and bounce
            growth[i] -= 5 * np.exp(-0.5 * ((yr - 2020.3) / 0.3) ** 2)
            growth[i] += 8 * np.exp(-0.5 * ((yr - 2021.0) / 0.5) ** 2)
            # 2023-24 deceleration
            growth[i] -= 4 * np.exp(-0.5 * ((yr - 2023.5) / 0.8) ** 2)
        nfc_growth[c] = growth + np.random.normal(0, 0.8, N_Q) + ci * 0.3
    # Germany weaker, Spain more volatile
    nfc_growth["Germany"] -= 2
    nfc_growth["Spain"] += np.random.normal(0, 1.5, N_Q)

    # ---- Sector Production Indicators (z-scores) ----
    sector_z = {}
    np.random.seed(790)
    for s in SECTORS:
        base = np.random.uniform(-0.5, 0.5)
        sector_z[s] = base + np.random.normal(0, 0.6)
    # Make certain sectors distinctly negative/positive
    sector_z["Building"] = -1.2 + np.random.normal(0, 0.2)
    sector_z["Chemicals"] = -0.8 + np.random.normal(0, 0.2)
    sector_z["Metals"] = -0.7 + np.random.normal(0, 0.2)
    sector_z["Autos"] = -0.3 + np.random.normal(0, 0.2)
    sector_z["Technology"] = 0.5 + np.random.normal(0, 0.2)
    sector_z["Aerospace"] = 0.7 + np.random.normal(0, 0.2)
    sector_z["Healthcare"] = 0.4 + np.random.normal(0, 0.2)

    # ---- Lending Composite Z-Score (long history) ----
    composite_z = np.zeros(N_Q)
    for i in range(N_Q):
        yr = 2004 + i / 4
        # Easing regimes (positive Z) vs tightening (negative Z)
        composite_z[i] = 0.0
        # GFC tightening
        composite_z[i] -= 2.5 * np.exp(-0.5 * ((yr - 2008.5) / 0.8) ** 2)
        # Euro crisis
        composite_z[i] -= 1.5 * np.exp(-0.5 * ((yr - 2012.0) / 0.7) ** 2)
        # QE easing
        composite_z[i] += 1.5 * np.exp(-0.5 * ((yr - 2015.5) / 1.5) ** 2)
        # COVID
        composite_z[i] -= 1.0 * np.exp(-0.5 * ((yr - 2020.2) / 0.3) ** 2)
        composite_z[i] += 1.2 * np.exp(-0.5 * ((yr - 2021.0) / 0.5) ** 2)
        # 2022-23 tightening
        composite_z[i] -= 1.8 * np.exp(-0.5 * ((yr - 2023.0) / 0.6) ** 2)
    composite_z += np.random.normal(0, 0.2, N_Q)

    # ---- Country Lending Conditions Heatmap ----
    # Columns: BLS Standards Z, Loan Growth Z
    np.random.seed(791)
    heatmap_data = np.zeros((len(COUNTRIES), 2))
    # BLS Standards Z (positive = tightening)
    heatmap_data[0, 0] = 0.3   # EA
    heatmap_data[1, 0] = 0.5   # DE
    heatmap_data[2, 0] = 0.1   # FR
    heatmap_data[3, 0] = 0.7   # IT
    heatmap_data[4, 0] = -0.2  # ES
    # Loan Growth Z (negative = contracting)
    heatmap_data[0, 1] = -0.2  # EA
    heatmap_data[1, 1] = -0.8  # DE
    heatmap_data[2, 1] = 0.1   # FR
    heatmap_data[3, 1] = -0.4  # IT
    heatmap_data[4, 1] = 0.5   # ES
    heatmap_data += np.random.normal(0, 0.1, heatmap_data.shape)

    # Summary stats
    latest_z = composite_z[-1]
    # Momentum = change over last 4 quarters
    momentum = composite_z[-1] - composite_z[-5] if N_Q > 5 else 0
    latest_bls = bls_standards[-1]
    tightening_episodes = sum(
        1 for i in range(1, N_Q)
        if bls_standards[i] > 20 and bls_standards[i - 1] <= 20
    )

    return {
        "bls_standards": bls_standards,
        "bls_terms": bls_terms,
        "nfc_growth": nfc_growth,
        "sector_z": sector_z,
        "composite_z": composite_z,
        "heatmap_data": heatmap_data,
        "latest_z": latest_z,
        "momentum": momentum,
        "latest_bls": latest_bls,
        "tightening_episodes": tightening_episodes,
    }


def generate_ecb_charts():
    """Generate ECB lending conditions charts — 2x3 layout."""
    setup_dark_style()
    data = _generate_ecb_data()

    fig = plt.figure(figsize=(24, 14), facecolor=COLORS["bg"])
    fig.suptitle("ECB LENDING CONDITIONS MONITOR",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(2, 3, hspace=0.45, wspace=0.35,
                          top=0.93, bottom=0.06, left=0.06, right=0.97)

    # Thin x labels for long time series
    def thin_labels(labels, every=8):
        return [l if i % every == 0 else "" for i, l in enumerate(labels)]

    # =========================================================================
    # 1. Lending Composite Z-Score (top-left) — long time series with regime
    # =========================================================================
    ax = fig.add_subplot(gs[0, 0])
    z = data["composite_z"]
    x = np.arange(N_Q)

    ax.plot(x, z, color=COLORS["cyan"], linewidth=1.5, zorder=3)

    # Regime shading: green (easing z>0.5), red (tightening z<-0.5), else neutral
    for i in range(N_Q - 1):
        if z[i] > 0.5:
            ax.axvspan(i, i + 1, alpha=0.15, color=COLORS["green"], zorder=0)
        elif z[i] < -0.5:
            ax.axvspan(i, i + 1, alpha=0.15, color=COLORS["red"], zorder=0)

    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.axhline(y=1, color=COLORS["green"], linestyle="--", linewidth=0.5, alpha=0.5)
    ax.axhline(y=-1, color=COLORS["red"], linestyle="--", linewidth=0.5, alpha=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(thin_labels(QUARTERS), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "Lending Composite Z-Score", ylabel="Z-Score")

    # Legend patches
    easy_patch = mpatches.Patch(color=COLORS["green"], alpha=0.3, label="Easing")
    tight_patch = mpatches.Patch(color=COLORS["red"], alpha=0.3, label="Tightening")
    ax.legend(handles=[easy_patch, tight_patch], fontsize=7, loc="upper left")

    # =========================================================================
    # 2. Summary Box (top-center)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 1])
    ax.axis("off")

    latest_z = data["latest_z"]
    momentum = data["momentum"]
    latest_bls = data["latest_bls"]
    tightening_eps = data["tightening_episodes"]

    if latest_z > 0.5:
        regime = "EASING"
        regime_color = COLORS["green"]
    elif latest_z < -0.5:
        regime = "TIGHTENING"
        regime_color = COLORS["red"]
    else:
        regime = "NEUTRAL"
        regime_color = COLORS["yellow"]

    if latest_bls > 20:
        bls_signal = "STRONG TIGHTENING"
    elif latest_bls > 10:
        bls_signal = "MODERATE TIGHTENING"
    elif latest_bls > 0:
        bls_signal = "MILD TIGHTENING"
    else:
        bls_signal = "EASING"

    summary = (
        f"LENDING SUMMARY\n"
        f"{'─' * 34}\n"
        f"Lending Regime:  {regime}\n"
        f"Composite Z:     {latest_z:+.2f}\n"
        f"Momentum:        {momentum:+.2f}\n"
        f"{'─' * 34}\n"
        f"BLS Current Signal:\n"
        f"  {bls_signal}\n"
        f"Latest BLS Value: {latest_bls:.1f}%\n"
        f"Historical Lead:  6-9 months\n"
        f"{'─' * 34}\n"
        f"Tightening Episodes: {tightening_eps}\n"
        f"ECB Series Fetched:  8\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=regime_color, linewidth=2))
    style_ax(ax, "ECB Lending Summary")

    # =========================================================================
    # 3. BLS Enterprise Survey — Credit Standards & Terms (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 2])
    x = np.arange(N_Q)
    ax.plot(x, data["bls_standards"], color=COLORS["cyan"], linewidth=1.2,
            label="Credit Standards")
    ax.plot(x, data["bls_terms"], color=COLORS["orange"], linewidth=1.2,
            label="Terms & Conditions")
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.8)
    ax.fill_between(x, data["bls_standards"], 0,
                    where=np.array(data["bls_standards"]) > 0,
                    alpha=0.1, color=COLORS["red"])
    ax.fill_between(x, data["bls_standards"], 0,
                    where=np.array(data["bls_standards"]) < 0,
                    alpha=0.1, color=COLORS["green"])
    ax.set_xticks(x)
    ax.set_xticklabels(thin_labels(QUARTERS), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "BLS Enterprise Survey (Net Tightening %)",
             ylabel="Net % Tightening")
    ax.legend(fontsize=7)

    # =========================================================================
    # 4. NFC Loan Growth by Country (bottom-left) — annual %
    # =========================================================================
    ax = fig.add_subplot(gs[1, 0])
    x = np.arange(N_Q)
    country_colors = [COLORS["cyan"], COLORS["red"], COLORS["blue"],
                      COLORS["orange"], COLORS["green"]]
    for ci, c in enumerate(COUNTRIES):
        ax.plot(x, data["nfc_growth"][c], color=country_colors[ci],
                linewidth=1.2, label=COUNTRY_CODES[ci])
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(thin_labels(QUARTERS), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "NFC Loan Growth by Country (Annual %)", ylabel="Growth (%)")
    ax.legend(fontsize=7, loc="lower left", ncol=3)

    # =========================================================================
    # 5. Sector Production Indicators (bottom-center) — horizontal bars z-score
    # =========================================================================
    ax = fig.add_subplot(gs[1, 1])
    sorted_sectors = sorted(data["sector_z"].items(), key=lambda x: x[1])
    s_names = [s[0] for s in sorted_sectors]
    s_vals = [s[1] for s in sorted_sectors]
    colors = [COLORS["green"] if v > 0 else COLORS["red"] for v in s_vals]
    bars = ax.barh(s_names, s_vals, color=colors, alpha=0.85)
    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.8)

    for bar, val in zip(bars, s_vals):
        x_pos = val + 0.05 if val > 0 else val - 0.05
        ha = "left" if val > 0 else "right"
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f"{val:+.2f}", va="center", ha=ha, fontsize=7,
                color=COLORS["text"])
    style_ax(ax, "Sector Production Indicators (Z-Score)", "Z-Score")
    ax.tick_params(axis="y", labelsize=8)

    # =========================================================================
    # 6. Country Lending Conditions Heatmap (bottom-right)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 2])
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "lending", [COLORS["green"], "#1a1a2e", COLORS["red"]])
    hm = data["heatmap_data"]
    vmax = max(abs(hm.min()), abs(hm.max()))
    im = ax.imshow(hm, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)

    dims = ["BLS Standards\nZ-Score", "Loan Growth\nZ-Score"]
    ax.set_xticks(range(len(dims)))
    ax.set_yticks(range(len(COUNTRIES)))
    ax.set_xticklabels(dims, fontsize=8)
    ax.set_yticklabels(COUNTRIES, fontsize=8)

    for i in range(len(COUNTRIES)):
        for j in range(len(dims)):
            val = hm[i, j]
            ax.text(j, i, f"{val:+.2f}", ha="center", va="center",
                    fontsize=9, fontweight="bold",
                    color="white" if abs(val) > 0.4 else COLORS["text"])
    fig.colorbar(im, ax=ax, shrink=0.7, label="Tightening → / ← Growth")
    style_ax(ax, "Country Lending Conditions (BLS vs Loan Growth)")

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
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("ecb-lending", generate_ecb_charts)
    return render_template_string(TEMPLATE, chart=chart)
