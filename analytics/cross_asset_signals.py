"""
Cross-Asset Credit Signal Framework - iTraxx Focus
Route: /signals

Composite signal from VIX, term structure, rates curve, sovereign spreads,
FX, equity drawdown, copper/gold ratio, and Merton dislocation model.
"""

import numpy as np
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

signals_bp = Blueprint("cross_asset_signals", __name__)

# ---------------------------------------------------------------------------
# Simulated signal components (would connect to live feeds)
# ---------------------------------------------------------------------------
N_DAYS = 252


def _generate_signals():
    """Generate synthetic signal data for demonstration."""
    np.random.seed(123)
    t = np.arange(N_DAYS)

    vix = 18 + 8 * np.sin(t / 40) + np.random.normal(0, 2, N_DAYS)
    vix = np.clip(vix, 10, 50)

    vix_3m = vix * (0.85 + 0.15 * np.random.random(N_DAYS))
    vix_term = vix / vix_3m

    curve_2s10s = 0.5 - 0.8 * np.sin(t / 80) + np.random.normal(0, 0.15, N_DAYS)

    btp_bund = 150 + 60 * np.sin(t / 50) + np.random.normal(0, 15, N_DAYS)
    btp_bund = np.clip(btp_bund, 80, 300)

    eurusd = 1.08 + 0.05 * np.sin(t / 60) + np.random.normal(0, 0.005, N_DAYS)
    dxy = 104 - 3 * np.sin(t / 60) + np.random.normal(0, 0.5, N_DAYS)

    spx = 4800 * np.exp(np.cumsum(np.random.normal(0.0003, 0.01, N_DAYS)))
    spx_peak = np.maximum.accumulate(spx)
    spx_dd = (spx / spx_peak - 1) * 100

    cu_au = 4.5 + 0.5 * np.sin(t / 70) + np.random.normal(0, 0.1, N_DAYS)

    # Merton model: distance to default proxy
    merton_dd = 3.0 + 0.8 * np.sin(t / 45) + np.random.normal(0, 0.3, N_DAYS)

    # Euro HY OAS
    hy_oas = 350 + 80 * np.sin(t / 35) + np.random.normal(0, 15, N_DAYS)
    hy_oas = np.clip(hy_oas, 200, 600)

    # Composite signal
    z_vix = -(vix - np.mean(vix)) / np.std(vix)
    z_term = -(vix_term - np.mean(vix_term)) / np.std(vix_term)
    z_curve = (curve_2s10s - np.mean(curve_2s10s)) / np.std(curve_2s10s)
    z_btp = -(btp_bund - np.mean(btp_bund)) / np.std(btp_bund)
    z_spx = (spx_dd - np.mean(spx_dd)) / np.std(spx_dd)
    z_cuau = (cu_au - np.mean(cu_au)) / np.std(cu_au)
    z_merton = (merton_dd - np.mean(merton_dd)) / np.std(merton_dd)

    composite = (0.20 * z_vix + 0.15 * z_term + 0.15 * z_curve +
                 0.10 * z_btp + 0.10 * z_spx + 0.10 * z_cuau +
                 0.20 * z_merton)

    return {
        "vix": vix, "vix_3m": vix_3m, "vix_term": vix_term,
        "curve_2s10s": curve_2s10s, "btp_bund": btp_bund,
        "eurusd": eurusd, "dxy": dxy, "spx_dd": spx_dd,
        "cu_au": cu_au, "merton_dd": merton_dd, "hy_oas": hy_oas,
        "composite": composite,
        "components": {"VIX": z_vix, "Term Struct": z_term,
                       "2s10s": z_curve, "BTP-Bund": z_btp,
                       "SPX DD": z_spx, "Cu/Au": z_cuau,
                       "Merton": z_merton},
    }


def generate_signal_charts():
    """Generate all cross-asset signal charts."""
    setup_dark_style()
    data = _generate_signals()
    t = np.arange(N_DAYS)

    fig = plt.figure(figsize=(22, 16), facecolor=COLORS["bg"])
    fig.suptitle("CROSS-ASSET CREDIT SIGNAL FRAMEWORK — iTRAXX FOCUS",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    gs = fig.add_gridspec(4, 3, hspace=0.45, wspace=0.3,
                          top=0.93, bottom=0.05, left=0.06, right=0.97)

    # 1. Euro HY OAS vs Composite Signal (dual axis)
    ax = fig.add_subplot(gs[0, :2])
    ax2 = ax.twinx()
    ax.plot(t, data["hy_oas"], color=COLORS["cyan"], linewidth=1.5, label="Euro HY OAS")
    ax.fill_between(t, data["hy_oas"], alpha=0.1, color=COLORS["cyan"])
    ax2.plot(t, data["composite"], color=COLORS["orange"], linewidth=1.5, label="Composite Signal")
    ax2.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5, linestyle="--")
    ax2.fill_between(t, data["composite"], where=data["composite"] > 0,
                     alpha=0.15, color=COLORS["green"])
    ax2.fill_between(t, data["composite"], where=data["composite"] < 0,
                     alpha=0.15, color=COLORS["red"])
    style_ax(ax, "Euro HY OAS vs Composite Signal", "Days", "OAS (bps)")
    ax2.set_ylabel("Composite Z-Score", fontsize=9, color=COLORS["orange"])
    ax2.tick_params(colors=COLORS["orange"], labelsize=8)
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")
    # Current signal annotation
    cur_sig = data["composite"][-1]
    direction = "LEAN LONG" if cur_sig > 0 else "LEAN SHORT"
    ax.text(0.98, 0.95, f"Signal: {cur_sig:+.2f} ({direction})",
            transform=ax.transAxes, ha="right", va="top", fontsize=10,
            fontweight="bold",
            color=COLORS["green"] if cur_sig > 0 else COLORS["red"],
            bbox=dict(boxstyle="round,pad=0.3", facecolor=COLORS["panel"],
                      edgecolor=COLORS["grid"]))

    # 2. VIX
    ax = fig.add_subplot(gs[0, 2])
    ax.plot(t, data["vix"], color=COLORS["red"], linewidth=1.2)
    ax.fill_between(t, data["vix"], alpha=0.15, color=COLORS["red"])
    ax.axhline(y=25, color=COLORS["yellow"], linestyle="--", linewidth=0.8, label="Stress (25)")
    style_ax(ax, "VIX", "Days", "Level")
    ax.legend(fontsize=7)

    # 3. VIX/VIX3M Term Structure
    ax = fig.add_subplot(gs[1, 0])
    ax.plot(t, data["vix_term"], color=COLORS["purple"], linewidth=1.2)
    ax.axhline(y=1.0, color=COLORS["yellow"], linestyle="--", linewidth=0.8,
               label="Backwardation")
    ax.fill_between(t, data["vix_term"], 1.0,
                    where=data["vix_term"] > 1.0, alpha=0.2, color=COLORS["red"])
    ax.fill_between(t, data["vix_term"], 1.0,
                    where=data["vix_term"] <= 1.0, alpha=0.2, color=COLORS["green"])
    style_ax(ax, "VIX/VIX3M Term Structure", "Days", "Ratio")
    ax.legend(fontsize=7)

    # 4. US 2s10s Curve
    ax = fig.add_subplot(gs[1, 1])
    ax.plot(t, data["curve_2s10s"], color=COLORS["teal"], linewidth=1.2)
    ax.axhline(y=0, color=COLORS["red"], linestyle="--", linewidth=0.8, label="Inversion")
    ax.fill_between(t, data["curve_2s10s"], 0,
                    where=data["curve_2s10s"] > 0, alpha=0.2, color=COLORS["green"])
    ax.fill_between(t, data["curve_2s10s"], 0,
                    where=data["curve_2s10s"] < 0, alpha=0.2, color=COLORS["red"])
    style_ax(ax, "US 2s10s Curve", "Days", "Spread (%)")
    ax.legend(fontsize=7)

    # 5. BTP-Bund Spread
    ax = fig.add_subplot(gs[1, 2])
    ax.plot(t, data["btp_bund"], color=COLORS["orange"], linewidth=1.2)
    ax.axhline(y=200, color=COLORS["red"], linestyle="--", linewidth=0.8, label="Stress (200bp)")
    ax.fill_between(t, data["btp_bund"], alpha=0.1, color=COLORS["orange"])
    style_ax(ax, "BTP-Bund Spread", "Days", "Spread (bps)")
    ax.legend(fontsize=7)

    # 6. EUR/USD & DXY
    ax = fig.add_subplot(gs[2, 0])
    ax.plot(t, data["eurusd"], color=COLORS["cyan"], linewidth=1.2, label="EUR/USD")
    ax3 = ax.twinx()
    ax3.plot(t, data["dxy"], color=COLORS["yellow"], linewidth=1.2, label="DXY")
    ax3.tick_params(colors=COLORS["yellow"], labelsize=8)
    style_ax(ax, "EUR/USD & USD Index", "Days", "EUR/USD")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax3.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=7)

    # 7. S&P 500 Drawdown
    ax = fig.add_subplot(gs[2, 1])
    ax.fill_between(t, data["spx_dd"], alpha=0.5, color=COLORS["red"])
    ax.plot(t, data["spx_dd"], color=COLORS["red"], linewidth=1)
    ax.axhline(y=-10, color=COLORS["yellow"], linestyle="--", linewidth=0.8,
               label="Signal (-10%)")
    style_ax(ax, "S&P 500 Drawdown", "Days", "Drawdown (%)")
    ax.legend(fontsize=7)

    # 8. Copper/Gold Ratio
    ax = fig.add_subplot(gs[2, 2])
    ax.plot(t, data["cu_au"], color=COLORS["lime"], linewidth=1.2)
    ax.axhline(y=np.mean(data["cu_au"]), color=COLORS["text_dim"],
               linestyle="--", linewidth=0.8, label="5yr MA")
    style_ax(ax, "Copper/Gold Ratio", "Days", "Ratio")
    ax.legend(fontsize=7)

    # 9. Merton Dislocation Model
    ax = fig.add_subplot(gs[3, 0])
    ax.plot(t, data["merton_dd"], color=COLORS["blue"], linewidth=1.5)
    ax.axhline(y=2.0, color=COLORS["red"], linestyle="--", linewidth=0.8,
               label="Distress (<2)")
    ax.fill_between(t, data["merton_dd"], 2.0,
                    where=data["merton_dd"] < 2.0, alpha=0.3, color=COLORS["red"])
    style_ax(ax, "Merton Dislocation Model", "Days", "Distance to Default")
    ax.legend(fontsize=7)

    # 10. Backtest Signal Quintiles
    ax = fig.add_subplot(gs[3, 1:])
    composite = data["composite"]
    quintiles = np.percentile(composite, [20, 40, 60, 80])
    labels_q = ["Q1 (Bear)", "Q2", "Q3 (Neutral)", "Q4", "Q5 (Bull)"]
    # Simulate forward returns for each quintile
    np.random.seed(77)
    fwd_returns = [
        np.random.normal(-0.8, 1.2, 50),
        np.random.normal(-0.2, 0.8, 50),
        np.random.normal(0.1, 0.6, 50),
        np.random.normal(0.5, 0.7, 50),
        np.random.normal(1.2, 0.9, 50),
    ]
    bp = ax.boxplot(fwd_returns, labels=labels_q, patch_artist=True,
                    medianprops=dict(color=COLORS["yellow"], linewidth=2),
                    whiskerprops=dict(color=COLORS["text_dim"]),
                    capprops=dict(color=COLORS["text_dim"]),
                    flierprops=dict(markeredgecolor=COLORS["text_dim"], markersize=3))
    q_colors = [COLORS["red"], COLORS["orange"], COLORS["text_dim"],
                COLORS["cyan"], COLORS["green"]]
    for patch, color in zip(bp["boxes"], q_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    style_ax(ax, "Signal Quintile → Forward 1M Credit Returns (%)",
             "Signal Quintile", "Forward Return (%)")

    return fig_to_base64(fig)


TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>Cross-Asset Credit Signals</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1600px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="Signal Charts">
</body></html>
"""


@signals_bp.route("/signals")
def signals():
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("signals", generate_signal_charts)
    return render_template_string(TEMPLATE, chart=chart)
