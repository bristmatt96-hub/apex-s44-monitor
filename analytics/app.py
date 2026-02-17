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
    ]
    return render_template("index.html", tools=tools)


# Register blueprints
from analytics.cds_pricer import cds_bp
from analytics.backtest_engine import backtest_bp
from analytics.cross_asset_signals import signals_bp
from analytics.dispersion_monitor import dispersion_bp
from analytics.distressed_monitor import distressed_bp
from analytics.ecb_lending import ecb_bp

app.register_blueprint(cds_bp)
app.register_blueprint(backtest_bp)
app.register_blueprint(signals_bp)
app.register_blueprint(dispersion_bp)
app.register_blueprint(distressed_bp)
app.register_blueprint(ecb_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
