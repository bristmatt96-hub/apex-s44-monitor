"""
XO S44 Price Alert Monitor
Checks all 42 public tickers every 2 minutes for +/- 1% moves
Sends alerts directly to Telegram
"""

import json
import time
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration - NEVER hardcode credentials
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL = 120  # seconds (2 minutes)
THRESHOLD = 1.0  # percent

# Load tickers
TICKERS = {
    "AF.PA": "Air France-KLM",
    "CEC.DE": "Ceconomy",
    "AVOL.SW": "Avolta",
    "GRF.MC": "Grifols",
    "IGT": "IGT",
    "MMB.PA": "Lagardere",
    "LTMC.MI": "Lottomatica",
    "ONTEX.BR": "Ontex",
    "PTEC.L": "Playtech",
    "PFD.L": "Premier Foods",
    "REC.MI": "Recordati",
    "TUI.L": "TUI",
    "WIZZ.L": "Wizz Air",
    "CSTM": "Constellium",
    "CCK": "Crown Holdings",
    "FRVIA.PA": "Forvia",
    "HLAG.DE": "Hapag-Lloyd",
    "TATAMOTORS.NS": "Tata Motors (JLR)",
    "LXS.DE": "Lanxess",
    "METSB.HE": "Metsa Board",
    "OI": "O-I Glass",
    "RNO.PA": "Renault",
    "RXL.PA": "Rexel",
    "SHA.DE": "Schaeffler",
    "TKA.DE": "ThyssenKrupp",
    "FR.PA": "Valeo",
    "VOLCAR-B.ST": "Volvo Car",
    "WBD.MI": "Webuild",
    "ETL.PA": "Eutelsat",
    "ILD.PA": "Iliad",
    "NEXI.MI": "Nexi",
    "NOKIA.HE": "Nokia",
    "SESG.PA": "SES",
    "9984.T": "SoftBank",
    "TIT.MI": "Telecom Italia",
    "LBTYA": "Liberty Global",
    "WLN.PA": "Worldline",
    "ZEG.L": "Zegona",
    "CPI.PR": "CPI Property",
    "SBB-B.ST": "SBB",
    "PPC.AT": "PPC Greece",
    "SPM.MI": "Saipem"
}

# Store previous prices
previous_prices = {}

def send_telegram(message):
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM - NOT CONFIGURED] {message}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def get_prices():
    """Fetch current prices for all tickers"""
    try:
        import yfinance as yf
        tickers_str = " ".join(TICKERS.keys())
        data = yf.download(tickers_str, period="1d", interval="1m", progress=False)

        prices = {}
        if 'Close' in data.columns:
            for ticker in TICKERS.keys():
                try:
                    if ticker in data['Close'].columns:
                        price = data['Close'][ticker].dropna().iloc[-1]
                        prices[ticker] = float(price)
                except:
                    pass
        return prices
    except Exception as e:
        print(f"Error fetching prices: {e}")
        return {}

def check_alerts():
    """Check for price moves exceeding threshold"""
    global previous_prices

    current_prices = get_prices()
    alerts = []

    for ticker, price in current_prices.items():
        if ticker in previous_prices and previous_prices[ticker] > 0:
            prev_price = previous_prices[ticker]
            change_pct = ((price - prev_price) / prev_price) * 100

            if abs(change_pct) >= THRESHOLD:
                company = TICKERS.get(ticker, ticker)
                direction = "📈" if change_pct > 0 else "📉"

                alert_msg = f"""
{direction} <b>{company}</b> ({ticker})

Price: {price:.2f}
Change: {change_pct:+.2f}%
Time: {datetime.now().strftime('%H:%M:%S')}

{"⚠️ CREDIT NEGATIVE - Check for news" if change_pct < -1 else "✅ Positive move"}
"""
                alerts.append(alert_msg)
                print(f"ALERT: {company} moved {change_pct:+.2f}%")

    # Update previous prices
    previous_prices = current_prices

    return alerts

def main():
    print("=" * 50)
    print("XO S44 Price Alert Monitor")
    print("=" * 50)
    print(f"Monitoring {len(TICKERS)} tickers")
    print(f"Check interval: {CHECK_INTERVAL} seconds")
    print(f"Alert threshold: +/- {THRESHOLD}%")
    print("=" * 50)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n⚠️  Telegram not configured!")
        print("Set environment variables:")
        print("  export TELEGRAM_BOT_TOKEN='your_token'")
        print("  export TELEGRAM_CHAT_ID='your_chat_id'")
        print("Or add to .env file")
        print("\nRunning in test mode (alerts printed to console)\n")
    else:
        send_telegram("🚀 XO S44 Monitor started\nMonitoring 42 credits for +/- 1% moves")

    print("Fetching initial prices...")
    previous_prices.update(get_prices())
    print(f"Got prices for {len(previous_prices)} tickers\n")

    print("Monitoring started. Press Ctrl+C to stop.\n")

    while True:
        try:
            time.sleep(CHECK_INTERVAL)

            now = datetime.now()
            print(f"[{now.strftime('%H:%M:%S')}] Checking prices...")

            alerts = check_alerts()

            for alert in alerts:
                send_telegram(alert)

            if not alerts:
                print(f"  No alerts - all within threshold")

        except KeyboardInterrupt:
            print("\n\nMonitor stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
