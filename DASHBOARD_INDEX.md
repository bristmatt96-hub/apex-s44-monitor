# APEX Dashboards & Tools Index

All dashboards and tools in one place. Update this table when you add something new.

## Dashboards

| Dashboard | Folder | Status | Live URL |
|-----------|--------|--------|----------|
| HY Fair Value & Z-Score | `dashboards/credit-zscore/` | Pending | TBD |
| Trading Dashboard | `web/` | Live | https://dashboard.mb-trading.co.uk |

## Monitors

| Tool | File | Description |
|------|------|-------------|
| APEX Monitor | `apex_monitor.py` | Main Streamlit monitoring app |
| Credit Events | `monitors/credit_events_monitor.py` | Credit event tracker |
| Trade Workbench | `monitors/trade_workbench.py` | Trade analysis workbench |
| Trading Tools | `monitors/trading_tools.py` | Stress calculator, maturity visualizer |

## How to Add a New Dashboard

1. Create a folder under `dashboards/your-dashboard-name/`
2. Build your app (Streamlit, Next.js, static HTML, etc.)
3. Deploy it (Streamlit Cloud, Vercel, etc.)
4. Update this table with the folder and live URL
