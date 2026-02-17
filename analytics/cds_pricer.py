"""
CDS & Tranche Pricer - Gaussian Copula Engine
Route: /hy-fair-value

Prices iTraxx Main & Crossover tranches using 1-Factor Gaussian Copula model.
Computes base correlation smile, expected loss, spread delta (CS01),
correlation sensitivity (Rho01), tranche leverage (delta), and fair spreads.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from flask import Blueprint, render_template_string
from analytics.chart_utils import (
    make_figure, fig_to_base64, style_ax, COLORS, PALETTE, setup_dark_style
)
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

cds_bp = Blueprint("cds_pricer", __name__)

# ---------------------------------------------------------------------------
# iTraxx Index definitions
# ---------------------------------------------------------------------------
ITRAXX_MAIN = {
    "name": "Main",
    "n_names": 125,
    "avg_spread_bps": 57,
    "recovery": 0.40,
    "maturity": 5,
    "tranches": [
        {"name": "0-3%", "attach": 0.00, "detach": 0.03},
        {"name": "3-6%", "attach": 0.03, "detach": 0.06},
        {"name": "6-9%", "attach": 0.06, "detach": 0.09},
        {"name": "9-12%", "attach": 0.09, "detach": 0.12},
        {"name": "12-22%", "attach": 0.12, "detach": 0.22},
        {"name": "22-100%", "attach": 0.22, "detach": 1.00},
    ],
}

ITRAXX_XOVER = {
    "name": "Crossover",
    "n_names": 75,
    "avg_spread_bps": 277,
    "recovery": 0.35,
    "maturity": 5,
    "tranches": [
        {"name": "0-10%", "attach": 0.00, "detach": 0.10},
        {"name": "10-15%", "attach": 0.10, "detach": 0.15},
        {"name": "15-25%", "attach": 0.15, "detach": 0.25},
        {"name": "25-35%", "attach": 0.25, "detach": 0.35},
        {"name": "35-100%", "attach": 0.35, "detach": 1.00},
    ],
}


# ---------------------------------------------------------------------------
# Gaussian Copula engine
# ---------------------------------------------------------------------------
class GaussianCopulaEngine:
    """1-Factor Gaussian Copula for CDO tranche pricing."""

    def __init__(self, n_names, avg_spread_bps, recovery, maturity, n_quad=50):
        self.n_names = n_names
        self.avg_spread_bps = avg_spread_bps
        self.recovery = recovery
        self.maturity = maturity
        self.n_quad = n_quad
        self.hazard_rate = self._spread_to_hazard(avg_spread_bps)

    def _spread_to_hazard(self, spread_bps):
        """Convert CDS spread to hazard rate assuming flat curve."""
        spread = spread_bps / 10000.0
        return spread / (1.0 - self.recovery)

    def default_prob(self):
        """Cumulative default probability to maturity."""
        return 1.0 - np.exp(-self.hazard_rate * self.maturity)

    def conditional_default_prob(self, rho, m):
        """
        Conditional default probability given systematic factor m.
        P(default | M=m) = Phi((Phi^{-1}(p) - sqrt(rho)*m) / sqrt(1-rho))
        """
        p = self.default_prob()
        if p <= 0 or p >= 1:
            return p
        threshold = norm.ppf(p)
        sqrt_rho = np.sqrt(max(rho, 1e-10))
        sqrt_1_rho = np.sqrt(max(1.0 - rho, 1e-10))
        return norm.cdf((threshold - sqrt_rho * m) / sqrt_1_rho)

    def expected_tranche_loss(self, attach, detach, rho):
        """
        Compute expected tranche loss using Gauss-Hermite quadrature.
        """
        points, weights = np.polynomial.hermite.hermgauss(self.n_quad)
        # Transform from Hermite to standard normal
        m_vals = points * np.sqrt(2)
        w_vals = weights / np.sqrt(np.pi)

        total = 0.0
        width = detach - attach
        if width <= 0:
            return 0.0

        for m, w in zip(m_vals, w_vals):
            cond_p = self.conditional_default_prob(rho, m)
            # Expected portfolio loss (as fraction of notional)
            port_loss = (1.0 - self.recovery) * cond_p
            # Tranche loss
            tranche_loss = (min(max(port_loss - attach, 0), width)) / width
            total += w * tranche_loss

        return total

    def base_correlation(self, detach, target_el=None, rho_range=(0.01, 0.99)):
        """
        Find base correlation that reprices equity tranche [0, detach].
        If target_el is None, use market-implied EL from flat correlation.
        """
        if target_el is None:
            # Use a default flat correlation to get initial EL
            target_el = self.expected_tranche_loss(0, detach, 0.30)

        try:
            bc = brentq(
                lambda r: self.expected_tranche_loss(0, detach, r) - target_el,
                rho_range[0], rho_range[1], xtol=1e-6
            )
        except (ValueError, RuntimeError):
            bc = 0.30
        return bc

    def spread_delta_cs01(self, attach, detach, rho, bump_bps=1):
        """CS01: change in tranche EL per 1bp spread bump."""
        orig = self.expected_tranche_loss(attach, detach, rho)
        self.hazard_rate = self._spread_to_hazard(self.avg_spread_bps + bump_bps)
        bumped = self.expected_tranche_loss(attach, detach, rho)
        self.hazard_rate = self._spread_to_hazard(self.avg_spread_bps)
        return (bumped - orig) * 10000  # in bps

    def rho01(self, attach, detach, rho, bump=0.01):
        """Correlation sensitivity: change in EL per 1% correlation bump."""
        orig = self.expected_tranche_loss(attach, detach, rho)
        bumped = self.expected_tranche_loss(attach, detach, min(rho + bump, 0.99))
        return (bumped - orig) * 10000

    def tranche_leverage(self, attach, detach, rho):
        """Delta / leverage = CS01_tranche / CS01_index."""
        tranche_cs01 = self.spread_delta_cs01(attach, detach, rho)
        index_cs01 = self.spread_delta_cs01(0, 1.0, rho)
        if abs(index_cs01) < 1e-12:
            return 0.0
        return tranche_cs01 / index_cs01

    def price_all_tranches(self, tranches):
        """Price all tranches and return results dict."""
        results = []
        for t in tranches:
            a, d = t["attach"], t["detach"]
            # Use base correlation approach for equity, flat 0.30 otherwise
            rho = self.base_correlation(d) if a == 0 else 0.30
            el = self.expected_tranche_loss(a, d, rho)
            cs01 = self.spread_delta_cs01(a, d, rho)
            r01 = self.rho01(a, d, rho)
            lev = self.tranche_leverage(a, d, rho)
            fair_spread = el * 10000 / self.maturity if self.maturity > 0 else 0
            results.append({
                "name": t["name"],
                "attach": a,
                "detach": d,
                "rho": rho,
                "expected_loss": el,
                "cs01": cs01,
                "rho01": r01,
                "leverage": lev,
                "fair_spread_bps": fair_spread,
            })
        return results


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------
def generate_cds_charts(main_results, xover_results, main_engine, xover_engine):
    """Generate all charts for the CDS pricer page."""
    setup_dark_style()

    fig, axes = plt.subplots(3, 3, figsize=(20, 16), facecolor=COLORS["bg"])
    fig.suptitle("CDS & TRANCHE PRICER — GAUSSIAN COPULA ENGINE",
                 fontsize=18, fontweight="bold", color=COLORS["cyan"], y=0.98)

    # 1. Base Correlation Smile
    ax = axes[0, 0]
    detach_main = [r["detach"] * 100 for r in main_results]
    bc_main = []
    for r in main_results:
        bc = main_engine.base_correlation(r["detach"])
        bc_main.append(bc * 100)
    detach_xover = [r["detach"] * 100 for r in xover_results]
    bc_xover = []
    for r in xover_results:
        bc = xover_engine.base_correlation(r["detach"])
        bc_xover.append(bc * 100)
    ax.plot(detach_main, bc_main, "o-", color=COLORS["cyan"], label="Main", linewidth=2)
    ax.plot(detach_xover, bc_xover, "s--", color=COLORS["orange"], label="Crossover", linewidth=2)
    style_ax(ax, "Base Correlation Smile", "Detachment Point (%)", "Base Correlation (%)")
    ax.legend(fontsize=8)

    # 2. Tranche Expected Loss
    ax = axes[0, 1]
    x_m = range(len(main_results))
    x_x = range(len(xover_results))
    bars_m = ax.bar([i - 0.15 for i in x_m], [r["expected_loss"] * 100 for r in main_results],
                    width=0.3, color=COLORS["cyan"], alpha=0.8, label="Main")
    bars_x = ax.bar([i + 0.15 for i in x_x], [r["expected_loss"] * 100 for r in xover_results],
                    width=0.3, color=COLORS["orange"], alpha=0.8, label="Crossover")
    ax.set_xticks(range(max(len(main_results), len(xover_results))))
    labels = [r["name"] for r in main_results]
    if len(xover_results) > len(labels):
        labels = [r["name"] for r in xover_results]
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    style_ax(ax, "Tranche Expected Loss", "Detachment", "Expected Loss (%)")
    ax.legend(fontsize=8)

    # 3. Spread Delta (CS01) - Main
    ax = axes[0, 2]
    names = [r["name"] for r in main_results]
    cs01_vals = [r["cs01"] for r in main_results]
    colors_cs01 = [COLORS["green"] if v > 0 else COLORS["red"] for v in cs01_vals]
    ax.bar(names, cs01_vals, color=colors_cs01, alpha=0.85)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    style_ax(ax, "Spread Delta (CS01) — Main", "Tranche", "CS01 (bps)")
    ax.tick_params(axis="x", rotation=45)

    # 4. Correlation Sensitivity (Rho01) - Main
    ax = axes[1, 0]
    rho01_vals = [r["rho01"] for r in main_results]
    colors_rho = [COLORS["purple"] if v > 0 else COLORS["red"] for v in rho01_vals]
    ax.bar(names, rho01_vals, color=colors_rho, alpha=0.85)
    ax.axhline(y=0, color=COLORS["text_dim"], linewidth=0.5)
    style_ax(ax, "Correlation Sensitivity (Rho01) — Main", "Tranche", "Rho01 (bps)")
    ax.tick_params(axis="x", rotation=45)

    # 5. CDS Spread Distribution
    ax = axes[1, 1]
    np.random.seed(42)
    main_spreads = np.random.lognormal(
        np.log(main_engine.avg_spread_bps), 0.5, main_engine.n_names)
    xover_spreads = np.random.lognormal(
        np.log(xover_engine.avg_spread_bps), 0.6, xover_engine.n_names)
    ax.hist(main_spreads, bins=25, alpha=0.6, color=COLORS["cyan"],
            label=f"Main (n={main_engine.n_names})", density=True)
    ax.hist(xover_spreads, bins=25, alpha=0.6, color=COLORS["orange"],
            label=f"Xover (n={xover_engine.n_names})", density=True)
    style_ax(ax, "CDS Spread Distribution", "Spread (bps)", "Density")
    ax.legend(fontsize=8)

    # 6. iTraxx Index Levels (placeholder - would pull from ECB/Bloomberg)
    ax = axes[1, 2]
    ax.text(0.5, 0.5, "iTraxx Index Levels\n\nConnect to live data feed\nfor real-time levels",
            transform=ax.transAxes, ha="center", va="center",
            fontsize=11, color=COLORS["text_dim"],
            bbox=dict(boxstyle="round,pad=0.5", facecolor=COLORS["panel"],
                      edgecolor=COLORS["grid"]))
    style_ax(ax, "iTraxx Index Levels")

    # 7. Tranche Leverage (Delta) - Main
    ax = axes[2, 0]
    lev_vals = [r["leverage"] for r in main_results]
    bars = ax.bar(names, lev_vals, color=PALETTE[:len(names)], alpha=0.85)
    for bar, val in zip(bars, lev_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{val:.1f}x", ha="center", va="bottom", fontsize=8,
                color=COLORS["text"])
    style_ax(ax, "Tranche Leverage (Delta) — Main", "Tranche", "Leverage (x)")
    ax.tick_params(axis="x", rotation=45)

    # 8. Pricing Summary box
    ax = axes[2, 1]
    ax.axis("off")
    eq_main = main_results[0]
    eq_xover = xover_results[0]
    summary_text = (
        f"PRICING SUMMARY\n"
        f"{'─' * 36}\n"
        f"Main: {main_engine.n_names} names, avg spread {main_engine.avg_spread_bps}bps\n"
        f"Crossover: {xover_engine.n_names} names, avg spread {xover_engine.avg_spread_bps}bps\n"
        f"{'─' * 36}\n"
        f"Main Equity: EL={eq_main['expected_loss']:.2%}, "
        f"Delta={eq_main['leverage']:.1f}x\n"
        f"Xover Equity: EL={eq_xover['expected_loss']:.2%}, "
        f"Delta={eq_xover['leverage']:.1f}x\n"
        f"{'─' * 36}\n"
        f"Copula: 1-Factor Gaussian\n"
        f"Quadrature: {main_engine.n_quad} points\n"
        f"Recovery: Main={main_engine.recovery:.0%}, "
        f"Xover={xover_engine.recovery:.0%}"
    )
    ax.text(0.5, 0.5, summary_text, transform=ax.transAxes,
            ha="center", va="center", fontsize=10,
            fontfamily="monospace", color=COLORS["text"],
            bbox=dict(boxstyle="round,pad=0.8", facecolor=COLORS["panel"],
                      edgecolor=COLORS["cyan"], linewidth=1.5))

    # 9. Fair Spread by Tranche
    ax = axes[2, 2]
    x_m = range(len(main_results))
    x_x = range(len(xover_results))
    ax.bar([i - 0.15 for i in x_m],
           [r["fair_spread_bps"] for r in main_results],
           width=0.3, color=COLORS["cyan"], alpha=0.8, label="Main")
    ax.bar([i + 0.15 for i in x_x],
           [r["fair_spread_bps"] for r in xover_results],
           width=0.3, color=COLORS["orange"], alpha=0.8, label="Crossover")
    ax.set_xticks(range(max(len(main_results), len(xover_results))))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    style_ax(ax, "Fair Spread by Tranche", "Tranche", "Fair Spread (bps)")
    ax.legend(fontsize=8)

    fig.subplots_adjust(top=0.93, bottom=0.06, hspace=0.45, wspace=0.3)
    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
TEMPLATE = """
<!DOCTYPE html>
<html><head>
    <title>CDS & Tranche Pricer</title>
    <style>
        body { background: #0a0a0a; margin: 0; padding: 20px; font-family: sans-serif; }
        img { width: 100%%; max-width: 1400px; display: block; margin: 0 auto; }
        .back { color: #7b2ff7; text-decoration: none; font-size: 14px; }
        .back:hover { color: #00d4ff; }
    </style>
</head><body>
    <a class="back" href="/">&larr; Back to Analytics Suite</a>
    <img src="{{ chart }}" alt="CDS Pricer Charts">
</body></html>
"""


def compute_cds_chart():
    """Full CDS chart computation (engines + charts) for caching."""
    main_engine = GaussianCopulaEngine(
        ITRAXX_MAIN["n_names"], ITRAXX_MAIN["avg_spread_bps"],
        ITRAXX_MAIN["recovery"], ITRAXX_MAIN["maturity"]
    )
    xover_engine = GaussianCopulaEngine(
        ITRAXX_XOVER["n_names"], ITRAXX_XOVER["avg_spread_bps"],
        ITRAXX_XOVER["recovery"], ITRAXX_XOVER["maturity"]
    )
    main_results = main_engine.price_all_tranches(ITRAXX_MAIN["tranches"])
    xover_results = xover_engine.price_all_tranches(ITRAXX_XOVER["tranches"])
    return generate_cds_charts(main_results, xover_results, main_engine, xover_engine)


@cds_bp.route("/hy-fair-value")
def hy_fair_value():
    from analytics.chart_utils import chart_cache
    chart = chart_cache.get_or_compute("hy-fair-value", compute_cds_chart)
    return render_template_string(TEMPLATE, chart=chart)
