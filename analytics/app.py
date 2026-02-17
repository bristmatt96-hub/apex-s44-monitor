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
"""

from flask import Flask, render_template
import os

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
