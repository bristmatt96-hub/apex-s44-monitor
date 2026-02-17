"""
European Credit Cycle Dashboard — iTraxx Focus
Route: /credit-cycle

Credit cycle regime classification (EXPANSION/RECOVERY/DOWNTURN/CRISIS)
from FRED-sourced macro indicators with 15yr lookback. Euro HY OAS with
regime overlay, composite score & momentum, current z-scores, confidence
indicators, growth, policy rates, VIX, HY spread ratio, ISM.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches

credit_cycle_bp = Blueprint("credit_cycle", __name__)

# ---------------------------------------------------------------------------
# Simulated FRED-style data — 15yr monthly history (2011–2025)
# ---------------------------------------------------------------------------
N_MONTHS = 180  # 15 years
MONTHS = []
for y in range(2011, 2026):
    for m in range(1, 13):
        if y == 2025 and m > 12:
            break
        if len(MONTHS) >= N_MONTHS:
            break
        MONTHS.append(f"{y}-{m:02d}")

INDICATORS = [
    "VIX", "Fed Funds Rate", "Euro Area Consumer Confid.",
    "ECB Deposit Facility Rate", "US 2s10s Spread",
    "Euro Area Business Confid.", "Euro Industrial Production YoY",
    "Euro Real GDP YoY", "US ISM Manufacturing",
    "Euro HY OAS", "US HY OAS", "BTP-Bund Spread",
    "EUR/USD", "DXY Index", "Copper/Gold Ratio"
]


def _generate_credit_cycle_data():
    """Generate synthetic FRED-sourced credit cycle data."""
    np.random.seed(333)
    t = np.arange(N_MONTHS)
    yr = 2011 + t / 12

    # ---- Euro HY OAS (bps) ----
    hy_oas = np.zeros(N_MONTHS)
    for i in range(N_MONTHS):
        y = yr[i]
        hy_oas[i] = 350
        # Euro crisis widening
        hy_oas[i] += 250 * np.exp(-0.5 * ((y - 2012.0) / 0.5) ** 2)
        # 2015-16 energy/EM stress
        hy_oas[i] += 120 * np.exp(-0.5 * ((y - 2016.0) / 0.3) ** 2)
        # COVID
        hy_oas[i] += 500 * np.exp(-0.5 * ((y - 2020.25) / 0.15) ** 2)
        # 2022 rate shock
        hy_oas[i] += 150 * np.exp(-0.5 * ((y - 2022.5) / 0.4) ** 2)
        # Gradual tightening 2023-24
        hy_oas[i] -= 80 * np.clip(y - 2023.5, 0, 2)
    hy_oas += np.random.normal(0, 15, N_MONTHS)
    hy_oas = np.clip(hy_oas, 200, 1000)

    # ---- VIX ----
    vix = 16 + 5 * np.sin(t / 20) + np.random.normal(0, 2, N_MONTHS)
    # Spikes
    for spike_yr, mag in [(2012.0, 15), (2015.8, 12), (2018.1, 10),
                           (2020.25, 50), (2022.3, 15)]:
        vix += mag * np.exp(-0.5 * ((yr - spike_yr) / 0.15) ** 2)
    vix = np.clip(vix, 10, 80)

    # ---- Policy rates ----
    ecb_rate = np.zeros(N_MONTHS)
    for i in range(N_MONTHS):
        y = yr[i]
        if y < 2014.5:
            ecb_rate[i] = max(0.5 - 0.3 * (y - 2011), 0.05)
        elif y < 2022.0:
            ecb_rate[i] = max(-0.5 + 0.1 * np.sin((y - 2016) / 2), -0.5)
        else:
            ecb_rate[i] = min(-0.5 + 1.5 * (y - 2022.0), 4.0)
    ecb_rate += np.random.normal(0, 0.05, N_MONTHS)

    fed_rate = np.zeros(N_MONTHS)
    for i in range(N_MONTHS):
        y = yr[i]
        if y < 2015.5:
            fed_rate[i] = 0.25
        elif y < 2019.5:
            fed_rate[i] = 0.25 + min((y - 2015.5) * 0.6, 2.5)
        elif y < 2020.5:
            fed_rate[i] = max(2.5 - 3.0 * (y - 2019.5), 0.25)
        elif y < 2022.0:
            fed_rate[i] = 0.25
        else:
            fed_rate[i] = min(0.25 + 2.0 * (y - 2022.0), 5.5)
    fed_rate += np.random.normal(0, 0.05, N_MONTHS)

    # ---- Confidence indicators ----
    biz_conf = -5 + 10 * np.sin(t / 30) + np.random.normal(0, 3, N_MONTHS)
    biz_conf -= 20 * np.exp(-0.5 * ((yr - 2020.25) / 0.2) ** 2)
    cons_conf = -8 + 8 * np.sin(t / 25) + np.random.normal(0, 4, N_MONTHS)
    cons_conf -= 25 * np.exp(-0.5 * ((yr - 2020.25) / 0.2) ** 2)
    cons_conf -= 15 * np.exp(-0.5 * ((yr - 2022.5) / 0.4) ** 2)

    # ---- Growth ----
    gdp_yoy = 1.5 + 1.0 * np.sin(t / 40) + np.random.normal(0, 0.3, N_MONTHS)
    gdp_yoy -= 12 * np.exp(-0.5 * ((yr - 2020.25) / 0.15) ** 2)
    gdp_yoy += 8 * np.exp(-0.5 * ((yr - 2021.0) / 0.3) ** 2)

    ip_yoy = 1.0 + 2.0 * np.sin(t / 35) + np.random.normal(0, 0.5, N_MONTHS)
    ip_yoy -= 20 * np.exp(-0.5 * ((yr - 2020.25) / 0.15) ** 2)
    ip_yoy += 15 * np.exp(-0.5 * ((yr - 2021.0) / 0.3) ** 2)

    # ---- US ISM Manufacturing ----
    ism = 52 + 4 * np.sin(t / 30) + np.random.normal(0, 1, N_MONTHS)
    ism -= 10 * np.exp(-0.5 * ((yr - 2020.25) / 0.15) ** 2)

    # ---- Euro HY / US HY Spread Ratio ----
    us_hy = hy_oas * (0.85 + 0.1 * np.sin(t / 40)) + np.random.normal(0, 10, N_MONTHS)
    hy_ratio = hy_oas / np.clip(us_hy, 100, 2000)

    # ---- Composite credit cycle score ----
    z_vix = -(vix - np.mean(vix)) / np.std(vix)
    z_hy = -(hy_oas - np.mean(hy_oas)) / np.std(hy_oas)
    z_biz = (biz_conf - np.mean(biz_conf)) / np.std(biz_conf)
    z_cons = (cons_conf - np.mean(cons_conf)) / np.std(cons_conf)
    z_gdp = (gdp_yoy - np.mean(gdp_yoy)) / np.std(gdp_yoy)
    z_ism = (ism - np.mean(ism)) / np.std(ism)

    composite = (0.20 * z_vix + 0.25 * z_hy + 0.15 * z_biz +
                 0.10 * z_cons + 0.15 * z_gdp + 0.15 * z_ism)

    # Momentum (3-month change)
    momentum = np.zeros(N_MONTHS)
    for i in range(3, N_MONTHS):
        momentum[i] = composite[i] - composite[i - 3]

    # Regime classification
    regimes = []
    for c in composite:
        if c > 0.5:
            regimes.append("EXPANSION")
        elif c > -0.2:
            regimes.append("RECOVERY")
        elif c > -1.0:
            regimes.append("DOWNTURN")
        else:
            regimes.append("CRISIS")

    # Current z-scores for bar chart
    current_z = {
        "VIX": z_vix[-1],
        "Fed Funds Rate": -(fed_rate[-1] - np.mean(fed_rate)) / max(np.std(fed_rate), 0.01),
        "Euro Area Consumer Confid.": z_cons[-1],
        "ECB Deposit Facility Rate": -(ecb_rate[-1] - np.mean(ecb_rate)) / max(np.std(ecb_rate), 0.01),
        "US 2s10s Spread": np.random.normal(0.3, 0.5),
        "Euro Area Business Confid.": z_biz[-1],
        "Euro Industrial Prod. YoY": (ip_yoy[-1] - np.mean(ip_yoy)) / max(np.std(ip_yoy), 0.01),
        "Euro Real GDP YoY": z_gdp[-1],
        "US ISM Manufacturing": z_ism[-1],
        "Euro HY OAS": z_hy[-1],
        "US HY OAS": z_hy[-1] * 0.9 + np.random.normal(0, 0.1),
        "BTP-Bund Spread": np.random.normal(-0.3, 0.4),
        "EUR/USD": np.random.normal(0.1, 0.3),
        "DXY Index": np.random.normal(-0.2, 0.4),
        "Copper/Gold Ratio": np.random.normal(0.2, 0.3),
    }

    return {
        "hy_oas": hy_oas, "vix": vix,
        "ecb_rate": ecb_rate, "fed_rate": fed_rate,
        "biz_conf": biz_conf, "cons_conf": cons_conf,
        "gdp_yoy": gdp_yoy, "ip_yoy": ip_yoy,
        "ism": ism, "hy_ratio": hy_ratio,
        "composite": composite, "momentum": momentum,
        "regimes": regimes, "current_z": current_z,
    }


def generate_credit_cycle_charts():
    """Generate European credit cycle dashboard — 3x3 layout + regime summary."""
    setup_dark_style()
    data = _generate_credit_cycle_data()

    fig = plt.figure(figsize=(26, 20), facecolor=COLORS["bg"])
    fig.suptitle("EUROPEAN CREDIT CYCLE DASHBOARD — iTRAXX FOCUS",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(3, 4, hspace=0.4, wspace=0.35,
                          top=0.94, bottom=0.04, left=0.06, right=0.97)

    t = np.arange(N_MONTHS)

    def thin_labels(labels, every=12):
        return [l if i % every == 0 else "" for i, l in enumerate(labels)]

    regime_colors_map = {
        "EXPANSION": COLORS["green"],
        "RECOVERY": COLORS["cyan"],
        "DOWNTURN": COLORS["orange"],
        "CRISIS": COLORS["red"],
    }

    # =========================================================================
    # 1. Euro HY OAS with Credit Cycle Regime Overlay (top, wide)
    # =========================================================================
    ax = fig.add_subplot(gs[0, :3])
    ax.plot(t, data["hy_oas"], color=COLORS["cyan"], linewidth=1.5, zorder=3)
    # Regime band shading
    for i in range(N_MONTHS - 1):
        rc = regime_colors_map.get(data["regimes"][i], COLORS["text_dim"])
        ax.axvspan(i, i + 1, alpha=0.12, color=rc, zorder=0)
    ax.set_xticks(t)
    ax.set_xticklabels(thin_labels(MONTHS), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "Euro HY OAS with Credit Cycle Regime Overlay",
             ylabel="OAS (bps)")

    # Legend
    patches = [mpatches.Patch(color=c, alpha=0.3, label=r)
               for r, c in regime_colors_map.items()]
    ax.legend(handles=patches, fontsize=7, loc="upper left", ncol=4)

    # =========================================================================
    # 2. Current Regime Summary Box (top-right)
    # =========================================================================
    ax = fig.add_subplot(gs[0, 3])
    ax.axis("off")

    current_regime = data["regimes"][-1]
    regime_color = regime_colors_map.get(current_regime, COLORS["yellow"])
    comp_val = data["composite"][-1]
    mom_val = data["momentum"][-1]

    if current_regime == "EXPANSION":
        stance = "LONG / CARRY"
    elif current_regime == "RECOVERY":
        stance = "SELECTIVE LONG"
    elif current_regime == "DOWNTURN":
        stance = "DEFENSIVE / SHORT"
    else:
        stance = "MAX DEFENSIVE"

    summary = (
        f"CURRENT REGIME\n"
        f"{'─' * 28}\n"
        f"{current_regime}\n"
        f"({stance})\n"
        f"{'─' * 28}\n"
        f"Composite: {comp_val:+.2f}\n"
        f"Momentum:  {mom_val:+.2f}\n"
        f"{'─' * 28}\n"
        f"Data source: FRED\n"
        f"Lookback: 15yr\n"
    )
    ax.text(0.5, 0.5, summary, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=regime_color, linewidth=2))
    style_ax(ax, "Regime Summary")

    # =========================================================================
    # 3. Credit Cycle Composite Score & Momentum (mid-left, wide)
    # =========================================================================
    ax = fig.add_subplot(gs[1, :2])
    ax.plot(t, data["composite"], color=COLORS["purple"], linewidth=1.5,
            label="Composite")
    ax.plot(t, data["momentum"], color=COLORS["orange"], linewidth=1.0,
            label="Momentum (3m)", alpha=0.7)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.axhline(y=0.5, color=COLORS["green"], linestyle="--", linewidth=0.5, alpha=0.5)
    ax.axhline(y=-0.2, color=COLORS["orange"], linestyle="--", linewidth=0.5, alpha=0.5)
    ax.axhline(y=-1.0, color=COLORS["red"], linestyle="--", linewidth=0.5, alpha=0.5)
    ax.fill_between(t, data["composite"], where=np.array(data["composite"]) > 0.5,
                    alpha=0.1, color=COLORS["green"])
    ax.fill_between(t, data["composite"], where=np.array(data["composite"]) < -1.0,
                    alpha=0.1, color=COLORS["red"])
    ax.set_xticks(t)
    ax.set_xticklabels(thin_labels(MONTHS), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "Credit Cycle Composite Score & Momentum", ylabel="Z-Score")
    ax.legend(fontsize=7)

    # =========================================================================
    # 4. Current Z-Scores (mid-right)
    # =========================================================================
    ax = fig.add_subplot(gs[1, 2:])
    sorted_z = sorted(data["current_z"].items(), key=lambda x: x[1])
    z_names = [z[0] for z in sorted_z]
    z_vals = [z[1] for z in sorted_z]
    z_colors = [COLORS["green"] if v > 0 else COLORS["red"] for v in z_vals]
    ax.barh(z_names, z_vals, color=z_colors, alpha=0.85)
    ax.axvline(x=0, color=COLORS["text_dim"], linewidth=0.8)
    for i, v in enumerate(z_vals):
        ha = "left" if v > 0 else "right"
        offset = 0.05 if v > 0 else -0.05
        ax.text(v + offset, i, f"{v:+.2f}", va="center", ha=ha,
                fontsize=6, color=COLORS["text"])
    style_ax(ax, "Current Z-Scores", "Z-Score")
    ax.tick_params(axis="y", labelsize=7)

    # =========================================================================
    # 5. Euro Confidence Indicators (bottom-left)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 0])
    ax.plot(t, data["biz_conf"], color=COLORS["cyan"], linewidth=1.2,
            label="Business")
    ax.plot(t, data["cons_conf"], color=COLORS["orange"], linewidth=1.2,
            label="Consumer")
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(t)
    ax.set_xticklabels(thin_labels(MONTHS, 24), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "Euro Confidence Indicators", ylabel="Level")
    ax.legend(fontsize=7)

    # =========================================================================
    # 6. Euro Growth YoY (bottom, second)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 1])
    ax.plot(t, data["gdp_yoy"], color=COLORS["green"], linewidth=1.2,
            label="Real GDP YoY")
    ax.plot(t, data["ip_yoy"], color=COLORS["purple"], linewidth=1.0,
            label="Industrial Prod", alpha=0.8)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(t)
    ax.set_xticklabels(thin_labels(MONTHS, 24), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "Euro Growth YoY%", ylabel="% YoY")
    ax.legend(fontsize=7)

    # =========================================================================
    # 7. Policy Rates (bottom, third)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 2])
    ax.plot(t, data["ecb_rate"], color=COLORS["cyan"], linewidth=1.5,
            label="ECB Deposit")
    ax.plot(t, data["fed_rate"], color=COLORS["orange"], linewidth=1.5,
            label="Fed Funds")
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    ax.set_xticks(t)
    ax.set_xticklabels(thin_labels(MONTHS, 24), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "Policy Rates (ECB vs Fed)", ylabel="Rate (%)")
    ax.legend(fontsize=7)

    # =========================================================================
    # 8. VIX with 20/30 levels (bottom, fourth)
    # =========================================================================
    ax = fig.add_subplot(gs[2, 3])
    ax.plot(t, data["vix"], color=COLORS["red"], linewidth=1.2)
    ax.fill_between(t, data["vix"], alpha=0.1, color=COLORS["red"])
    ax.axhline(y=20, color=COLORS["yellow"], linestyle="--", linewidth=0.7, label="20")
    ax.axhline(y=30, color=COLORS["red"], linestyle="--", linewidth=0.7, label="30")
    ax.set_xticks(t)
    ax.set_xticklabels(thin_labels(MONTHS, 24), rotation=45, ha="right", fontsize=6)
    style_ax(ax, "VIX", ylabel="Level")
    ax.legend(fontsize=7)

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>European Credit Cycle Dashboard</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1800px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Credit Cycle Charts">
</body></html>
"""


@credit_cycle_bp.route("/credit-cycle")
def credit_cycle():
    chart = generate_credit_cycle_charts()
    return render_template_string(TEMPLATE, chart=chart)
