"""
Credit Catalyst -- FastAPI Web Dashboard Backend

Serves a single-page HTML dashboard and JSON API endpoints
for the Credit Catalyst European credit relative value platform.

API Endpoints:
    GET /                          -- Dashboard HTML
    GET /api/universe              -- Universe screen (75 names)
    GET /api/portfolio             -- Current portfolio (10 positions)
    GET /api/risk                  -- Risk metrics + limits
    GET /api/filings               -- Latest filing alerts
    GET /api/relative-value        -- Rich/cheap screen
    GET /api/maturity-wall         -- Top refinancing risk names
    GET /api/dispersion            -- Spread dispersion regime
    GET /api/scenarios             -- Stress scenario P&L

Usage:
    python -m app.api.main
    -> http://localhost:8000
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Credit Catalyst",
    description="European Credit Relative Value Dashboard",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_latest(pattern: str, directory: str = "outputs") -> Path | None:
    """Find latest file matching glob pattern."""
    d = Path(directory)
    if not d.exists():
        return None
    candidates = sorted(
        d.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_json(path: Path) -> dict:
    """Load JSON file."""
    with open(path) as f:
        return json.load(f)


def load_xover_screen() -> list[dict]:
    """Load all 75 names from latest xover screen Excel."""
    path = find_latest("xover_screen_*.xlsx")
    if not path:
        return []
    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    names = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        spread = float(row[4]) if row[4] is not None else 0.0
        if spread <= 0:
            continue
        names.append({
            "entity_name": str(row[0]).strip(),
            "direction": str(row[1] or "").strip(),
            "conviction": int(row[2]) if row[2] is not None else 3,
            "raw_conviction": int(row[3]) if row[3] is not None else 3,
            "current_spread": spread,
            "fair_spread": float(row[5]) if row[5] is not None else spread,
            "mispricing_bps": float(row[6]) if row[6] is not None else 0,
            "rel_mispricing_pct": float(row[7]) if row[7] is not None else 0,
            "thesis": str(row[8] or "")[:200],
            "catalyst": str(row[9] or "")[:200],
        })
    wb.close()
    return names


# ---------------------------------------------------------------------------
# Routes -- Dashboard HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the single-page dashboard."""
    html_path = PROJECT_ROOT / "app" / "web" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)


# ---------------------------------------------------------------------------
# Routes -- API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/universe")
async def api_universe():
    """Full universe screen -- 75 names with spreads, conviction, thesis."""
    names = load_xover_screen()

    longs = [n for n in names if n["direction"] == "LONG_RISK"]
    shorts = [n for n in names if n["direction"] == "SHORT_RISK"]

    # Top ideas by conviction then mispricing
    top_longs = sorted(longs, key=lambda x: (-x["conviction"], -abs(x["mispricing_bps"])))[:5]
    top_shorts = sorted(shorts, key=lambda x: (-x["conviction"], -abs(x["mispricing_bps"])))[:5]

    avg_spread = sum(n["current_spread"] for n in names) / len(names) if names else 0
    avg_conviction = sum(n["conviction"] for n in names) / len(names) if names else 0

    return {
        "count": len(names),
        "long_count": len(longs),
        "short_count": len(shorts),
        "avg_spread": round(avg_spread, 1),
        "avg_conviction": round(avg_conviction, 1),
        "top_longs": top_longs,
        "top_shorts": top_shorts,
        "all_names": names,
    }


@app.get("/api/portfolio")
async def api_portfolio():
    """Current portfolio from strategist output."""
    path = find_latest("portfolio_*.json", "outputs/portfolio")
    if not path:
        return {"error": "No portfolio found"}

    portfolio = load_json(path)
    positions = portfolio.get("top_positions", [])
    hedges = portfolio.get("hedges", [])
    risk = portfolio.get("risk_summary", {})
    stress = portfolio.get("stress_scenarios", [])

    return {
        "date": portfolio.get("portfolio_date", ""),
        "nav_millions": portfolio.get("nav_millions", 500),
        "positions": positions,
        "hedges": hedges,
        "risk_summary": risk,
        "stress_scenarios": stress,
        "net_bias": portfolio.get("net_bias", {}),
        "sector_allocation": portfolio.get("sector_allocation", {}),
        "pair_trades": portfolio.get("pair_trades", []),
    }


@app.get("/api/risk")
async def api_risk():
    """Risk metrics from risk snapshot and risk report."""
    # Risk snapshot
    snap_path = find_latest("risk_snapshot_*.json", "outputs/portfolio")
    snap = load_json(snap_path) if snap_path else {}

    # Portfolio for DV01/JTD calculations
    port_path = find_latest("portfolio_*.json", "outputs/portfolio")
    portfolio = load_json(port_path) if port_path else {}
    positions = portfolio.get("top_positions", [])
    nav_m = portfolio.get("nav_millions", 500)

    # Compute risk metrics from CDS pricer
    try:
        from analytics.cds_pricer import cds_dv01, cds_cs01, jump_to_default
        total_dv01 = 0
        total_cs01 = 0
        total_jtd_gross = 0
        position_risks = []

        for p in positions:
            spread = p.get("current_spread", 0)
            notional = abs(p.get("notional_millions", 0)) * 1_000_000
            direction = p.get("direction", "LONG_RISK")
            is_prot_buyer = direction == "SHORT_RISK"

            if spread > 0 and notional > 0:
                dv01 = cds_dv01(spread, notional=notional)
                cs01 = cds_cs01(spread, notional=notional)
                jtd = jump_to_default(spread, notional=notional,
                                      is_protection_buyer=is_prot_buyer)
                signed_dv01 = dv01 if is_prot_buyer else -dv01

                total_dv01 += signed_dv01
                total_cs01 += cs01
                total_jtd_gross += abs(jtd)

                position_risks.append({
                    "entity_name": p.get("entity_name"),
                    "direction": direction,
                    "notional_m": p.get("notional_millions"),
                    "spread": spread,
                    "dv01": round(dv01),
                    "signed_dv01": round(signed_dv01),
                    "jtd": round(jtd),
                })
    except Exception:
        total_dv01 = total_cs01 = total_jtd_gross = 0
        position_risks = []

    # Risk limits with traffic lights
    sector_conc = snap.get("sector_concentration", {})
    max_sector = max(sector_conc.values()) if sector_conc else 0
    jtd_pct = total_jtd_gross / (nav_m * 1_000_000) * 100 if nav_m > 0 else 0

    limits = [
        {
            "metric": "Net Exposure",
            "current": abs(snap.get("net_exposure", 0)),
            "limit": 50,
            "unit": "%",
            "status": "GREEN" if abs(snap.get("net_exposure", 0)) < 42.5 else
                      "AMBER" if abs(snap.get("net_exposure", 0)) < 50 else "RED",
        },
        {
            "metric": "Gross Exposure",
            "current": snap.get("gross_exposure", 0),
            "limit": 200,
            "unit": "%",
            "status": "GREEN" if snap.get("gross_exposure", 0) < 170 else
                      "AMBER" if snap.get("gross_exposure", 0) < 200 else "RED",
        },
        {
            "metric": "Max Sector",
            "current": round(max_sector, 1),
            "limit": 25,
            "unit": "%",
            "status": "GREEN" if max_sector < 21.25 else
                      "AMBER" if max_sector < 25 else "RED",
        },
        {
            "metric": "Net DV01",
            "current": round(total_dv01),
            "limit": 100000,
            "unit": "$",
            "status": "GREEN" if abs(total_dv01) < 85000 else
                      "AMBER" if abs(total_dv01) < 100000 else "RED",
        },
        {
            "metric": "JTD Gross % NAV",
            "current": round(jtd_pct, 1),
            "limit": 15,
            "unit": "%",
            "status": "GREEN" if jtd_pct < 12.75 else
                      "AMBER" if jtd_pct < 15 else "RED",
        },
    ]

    return {
        "total_dv01": round(total_dv01),
        "total_cs01": round(total_cs01),
        "total_jtd_gross": round(total_jtd_gross),
        "jtd_pct_nav": round(jtd_pct, 2),
        "sector_concentration": sector_conc,
        "rating_buckets": snap.get("rating_buckets", {}),
        "gross_exposure": snap.get("gross_exposure", 0),
        "net_exposure": snap.get("net_exposure", 0),
        "risk_limits": limits,
        "position_risks": position_risks,
    }


@app.get("/api/filings")
async def api_filings():
    """Latest filing alerts from European monitor."""
    db_path = PROJECT_ROOT / "data" / "filings.db"
    if not db_path.exists():
        return {"filings": [], "count": 0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT company_name, matched_entity, source, filing_type,
               headline, date, url, credit_impact, severity,
               credit_summary, created_at
        FROM filings
        ORDER BY date DESC, created_at DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    filings = [dict(r) for r in rows]
    return {"filings": filings, "count": len(filings)}


@app.get("/api/screen")
async def api_screen():
    """Alias for /api/universe -- top ideas data."""
    return await api_universe()


@app.get("/api/rv")
async def api_rv():
    """Alias for /api/relative-value."""
    return await api_relative_value()


@app.get("/api/maturity")
async def api_maturity():
    """Alias for /api/maturity-wall."""
    return await api_maturity_wall()


@app.get("/api/relative-value")
async def api_relative_value():
    """Rich/cheap screen from relative value module."""
    try:
        from analytics.relative_value import run_full_analysis
        assessed, pairs = run_full_analysis()
        if not assessed:
            return {"error": "No market data"}

        cheap = sorted(
            [n for n in assessed if "cheap" in n.rv_signal.lower()],
            key=lambda x: -x.composite_score,
        )[:5]
        rich = sorted(
            [n for n in assessed if "rich" in n.rv_signal.lower()],
            key=lambda x: x.composite_score,
        )[:5]

        return {
            "top_cheap": [
                {
                    "entity_name": n.entity_name,
                    "sector": n.sector,
                    "spread": n.current_spread,
                    "composite_score": round(n.composite_score, 2),
                    "signal": n.rv_signal,
                    "sector_z": round(n.sector_z, 2),
                    "rating_z": round(n.rating_z, 2),
                }
                for n in cheap
            ],
            "top_rich": [
                {
                    "entity_name": n.entity_name,
                    "sector": n.sector,
                    "spread": n.current_spread,
                    "composite_score": round(n.composite_score, 2),
                    "signal": n.rv_signal,
                    "sector_z": round(n.sector_z, 2),
                    "rating_z": round(n.rating_z, 2),
                }
                for n in rich
            ],
            "total_cheap": len([n for n in assessed if "cheap" in n.rv_signal.lower()]),
            "total_rich": len([n for n in assessed if "rich" in n.rv_signal.lower()]),
            "total_fair": len([n for n in assessed if n.rv_signal.upper() == "FAIR"]),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/maturity-wall")
async def api_maturity_wall():
    """Top names with highest refinancing risk."""
    try:
        from analytics.maturity_wall import load_maturity_data, extract_maturity_entries
        data = load_maturity_data()
        entries = extract_maturity_entries(data)

        # Sort by risk score descending
        entries.sort(key=lambda x: x.get("risk_score", 0), reverse=True)

        return {
            "entries": entries[:10],
            "total": len(entries),
        }
    except Exception as e:
        # Fallback: use high-spread names from portfolio as proxy
        try:
            names = load_xover_screen()
            high_spread = sorted(names, key=lambda x: -x["current_spread"])[:5]
            return {
                "entries": [
                    {
                        "entity_name": n["entity_name"],
                        "current_spread": n["current_spread"],
                        "refi_risk": "HIGH" if n["current_spread"] > 800 else
                                     "MEDIUM" if n["current_spread"] > 500 else "LOW",
                        "note": f"Spread {n['current_spread']:.0f}bp implies elevated refinancing cost",
                    }
                    for n in high_spread
                ],
                "total": len(high_spread),
                "source": "spread-implied",
            }
        except Exception:
            return {"entries": [], "total": 0, "error": str(e)}


@app.get("/api/dispersion")
async def api_dispersion():
    """Spread dispersion regime."""
    try:
        from analytics.dispersion import load_spread_data, run_dispersion_analysis
        names = load_spread_data()
        report = run_dispersion_analysis(names)

        return {
            "regime": report.regime,
            "regime_description": report.regime_description,
            "universe_cv": round(report.universe_stats.cv, 3),
            "universe_mean": round(report.universe_stats.mean_spread, 1),
            "universe_stdev": round(report.universe_stats.stdev_spread, 1),
            "sectors": [
                {
                    "name": s.group_name,
                    "count": s.count,
                    "cv": round(s.cv, 2),
                    "mean": round(s.mean_spread, 1),
                    "regime": s.regime,
                }
                for s in sorted(report.sector_stats, key=lambda x: -x.cv)
            ],
            "pair_trade_sectors": report.pair_trade_sectors,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/scenarios")
async def api_scenarios():
    """Stress scenario P&L summary."""
    try:
        from analytics.scenario_analysis import (
            find_latest_portfolio as sa_find,
            load_portfolio as sa_load,
            load_sector_mapping,
            run_all_scenarios,
        )
        path = sa_find()
        if not path:
            return {"error": "No portfolio"}
        portfolio = sa_load(path)
        sector_map = load_sector_mapping()
        results = run_all_scenarios(portfolio, sector_map)
        nav = portfolio.get("nav_millions", 500) * 1_000_000

        return {
            "scenarios": [
                {
                    "id": r.scenario_id,
                    "name": r.name,
                    "description": r.description,
                    "portfolio_pnl": round(r.total_pnl),
                    "hedge_pnl": round(r.hedge_pnl),
                    "combined_pnl": round(r.combined_pnl),
                    "pct_nav": round(r.combined_pnl / nav * 100, 2) if nav else 0,
                    "worst_position": r.worst_position,
                }
                for r in results
            ],
            "worst_scenario": min(results, key=lambda r: r.combined_pnl).name,
            "best_scenario": max(results, key=lambda r: r.combined_pnl).name,
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  CREDIT CATALYST -- Web Dashboard")
    print("  http://localhost:8000")
    print("=" * 60 + "\n")
    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
