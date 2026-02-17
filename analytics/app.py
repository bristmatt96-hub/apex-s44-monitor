"""
APEX S44 Analytics Suite
========================
Flask application serving all analytical tools:
  /hy-fair-value     - CDS & Tranche Pricer (Gaussian Copula Engine)
  /backtest          - Credit Backtest Engine
  /signals           - Cross-Asset Credit Signal Framework (iTraxx Focus)
  /dispersion        - Dispersion & Correlation Monitor
  /distressed        - Distressed / LME Monitor (iTraxx Crossover Universe)
  /ecb-lending       - ECB Lending Conditions Monitor
  /equity-signals    - Equity-Implied Credit Signals (iTraxx Crossover)
  /credit-cycle      - European Credit Cycle Dashboard (iTraxx Focus)
  /fallen-angels     - Fallen Angel / Rising Star Screener (iTraxx Crossover)
  /risk-manager      - Portfolio Risk Manager
  /fundamentals      - Fundamental Credit Analysis (iTraxx Crossover)
  /maturity-wall     - HY Maturity Wall & Refinancing Dashboard
  /relative-value    - Relative Value Analysis (iTraxx Crossover)
  /scenario-analysis - Scenario Analysis Engine
  /tranche-strategy  - Tranche Strategy Engine
"""

import logging
import threading
import time

from flask import Flask, render_template

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/")
def index():
    """Landing page with links to all tools."""
    tools = [
        {"path": "/hy-fair-value", "name": "CDS & Tranche Pricer",
         "desc": "Gaussian Copula Engine - iTraxx Main & Crossover tranche pricing"},
        {"path": "/backtest", "name": "Credit Backtest Engine",
         "desc": "Strategy backtesting with Sharpe ratios, hit rates & P&L curves"},
        {"path": "/signals", "name": "Cross-Asset Credit Signal Framework",
         "desc": "iTraxx composite signal from VIX, rates, FX, equity & Merton model"},
        {"path": "/dispersion", "name": "Dispersion & Correlation Monitor",
         "desc": "Implied vs realized correlation, sector spread dispersion"},
        {"path": "/distressed", "name": "Distressed / LME Monitor",
         "desc": "iTraxx Crossover liquidity stress, cash burn & sector distress"},
        {"path": "/ecb-lending", "name": "ECB Lending Conditions Monitor",
         "desc": "BLS survey, NFC loan growth, sector production & country heatmap"},
        {"path": "/equity-signals", "name": "Equity-Implied Credit Signals",
         "desc": "iTraxx Crossover composite from Vol, Momentum, Drawdown, Leverage, Beta"},
        {"path": "/credit-cycle", "name": "European Credit Cycle Dashboard",
         "desc": "FRED-sourced regime classification: Expansion/Recovery/Downturn/Crisis"},
        {"path": "/fallen-angels", "name": "Fallen Angel / Rising Star Screener",
         "desc": "FA risk scoring, RS potential, component breakdowns & alert table"},
        {"path": "/risk-manager", "name": "Portfolio Risk Manager",
         "desc": "Greeks, risk limits, JTD, VaR/CVaR, stress tests, margin utilization"},
        {"path": "/fundamentals", "name": "Fundamental Credit Analysis",
         "desc": "Leverage, coverage, FCF/Debt, sector quality heatmap for 61 names"},
        {"path": "/maturity-wall", "name": "HY Maturity Wall & Refinancing",
         "desc": "US/EUR HY maturity walls, refi yields, stress scenarios, ICR, FA risk"},
        {"path": "/relative-value", "name": "Relative Value Analysis",
         "desc": "Rich/cheap scoring, Merton spreads, spread per leverage, sector RV"},
        {"path": "/scenario-analysis", "name": "Scenario Analysis Engine",
         "desc": "Macro scenario P&L, probability-weighted returns, hedge effectiveness"},
        {"path": "/tranche-strategy", "name": "Tranche Strategy Engine",
         "desc": "P&L waterfall, signal dashboard, delta hedge, stress & carry analysis"},
    ]
    return render_template("index.html", tools=tools)


# Register blueprints
from analytics.cds_pricer import cds_bp
from analytics.backtest_engine import backtest_bp
from analytics.cross_asset_signals import signals_bp
from analytics.dispersion_monitor import dispersion_bp
from analytics.distressed_monitor import distressed_bp
from analytics.ecb_lending import ecb_bp
from analytics.equity_signals import equity_signals_bp
from analytics.credit_cycle import credit_cycle_bp
from analytics.fallen_angels import fallen_angels_bp
from analytics.risk_manager import risk_bp
from analytics.fundamentals import fundamentals_bp
from analytics.maturity_wall import maturity_bp
from analytics.relative_value import rv_bp
from analytics.scenario_analysis import scenario_bp
from analytics.tranche_strategy import tranche_bp

app.register_blueprint(cds_bp)
app.register_blueprint(backtest_bp)
app.register_blueprint(signals_bp)
app.register_blueprint(dispersion_bp)
app.register_blueprint(distressed_bp)
app.register_blueprint(ecb_bp)
app.register_blueprint(equity_signals_bp)
app.register_blueprint(credit_cycle_bp)
app.register_blueprint(fallen_angels_bp)
app.register_blueprint(risk_bp)
app.register_blueprint(fundamentals_bp)
app.register_blueprint(maturity_bp)
app.register_blueprint(rv_bp)
app.register_blueprint(scenario_bp)
app.register_blueprint(tranche_bp)


# ---------------------------------------------------------------------------
# Chart pre-computation — warm cache on startup, refresh every 5 minutes
# ---------------------------------------------------------------------------
def _get_chart_generators():
    """Registry of all chart generator functions keyed by route name."""
    from analytics.cds_pricer import compute_cds_chart
    from analytics.backtest_engine import generate_backtest_charts
    from analytics.cross_asset_signals import generate_signal_charts
    from analytics.dispersion_monitor import generate_dispersion_charts
    from analytics.distressed_monitor import generate_distressed_charts
    from analytics.ecb_lending import generate_ecb_charts
    from analytics.equity_signals import generate_equity_signal_charts
    from analytics.credit_cycle import generate_credit_cycle_charts
    from analytics.fallen_angels import generate_fallen_angel_charts
    from analytics.risk_manager import generate_risk_charts
    from analytics.fundamentals import generate_fundamentals_charts
    from analytics.maturity_wall import generate_maturity_charts
    from analytics.relative_value import generate_rv_charts
    from analytics.scenario_analysis import generate_scenario_charts
    from analytics.tranche_strategy import generate_tranche_charts

    return {
        "hy-fair-value": compute_cds_chart,
        "backtest": generate_backtest_charts,
        "signals": generate_signal_charts,
        "dispersion": generate_dispersion_charts,
        "distressed": generate_distressed_charts,
        "ecb-lending": generate_ecb_charts,
        "equity-signals": generate_equity_signal_charts,
        "credit-cycle": generate_credit_cycle_charts,
        "fallen-angels": generate_fallen_angel_charts,
        "risk-manager": generate_risk_charts,
        "fundamentals": generate_fundamentals_charts,
        "maturity-wall": generate_maturity_charts,
        "relative-value": generate_rv_charts,
        "scenario-analysis": generate_scenario_charts,
        "tranche-strategy": generate_tranche_charts,
    }


def _precompute_loop(interval=300):
    """Background loop that pre-computes all charts on a schedule."""
    from analytics.chart_utils import chart_cache

    # Initial warm-up
    generators = _get_chart_generators()
    logger.info("Pre-computing %d analytics charts...", len(generators))
    chart_cache.precompute_all(generators)

    # Refresh loop
    while True:
        time.sleep(interval)
        logger.info("Refreshing analytics chart cache...")
        chart_cache.precompute_all(generators)


# Start background pre-computation thread (daemon so it dies with the app)
_precompute_thread = threading.Thread(
    target=_precompute_loop, daemon=True, name="chart-precompute")
_precompute_thread.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
