"""
Twitter Alpha Scanner for XO S44 Credits
Uses Grok (xAI) to periodically scan Twitter for credit-relevant posts
Sends Telegram alerts when interesting alpha is found

Run alongside price_alert_monitor.py for comprehensive coverage
"""

import os
import json
import time
import hashlib
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ============== CONFIGURATION ==============

# API Keys - set these or use environment variables
XAI_API_KEY = os.environ.get("XAI_API_KEY", "YOUR_XAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

# Scanning settings
SCAN_INTERVAL = 900  # 15 minutes (in seconds)
BATCH_SIZE = 10  # Number of companies to check per scan cycle

# XO S44 Companies to monitor (short names for Twitter search)
XO_S44_NAMES = [
    "Air France KLM", "Grifols", "IGT", "Lottomatica", "Playtech",
    "TUI", "Wizz Air", "Constellium", "Crown Holdings", "Forvia",
    "Hapag-Lloyd", "Jaguar Land Rover", "Lanxess", "ThyssenKrupp",
    "Renault", "Schaeffler", "Valeo", "Volvo Car", "Eutelsat",
    "Iliad", "Nokia", "SES", "SoftBank", "Telecom Italia",
    "Worldline", "Nexi", "CPI Property", "SBB Nordic", "Saipem",
    "Ceconomy", "Ontex", "Premier Foods", "Rexel", "Webuild"
]

# Curated HY/Credit Twitter accounts Grok should focus on
PRIORITY_ACCOUNTS = """
@CreditSights, @LevFinInsights, @Creditflux, @9finHQ, @DebtwireEurope,
@DeItaone, @FirstSquawk, @zerohedge, @unusual_whales, @Fxhedgers,
@PriapusIQ, @ResijsMarc, @RobinWigg, @bondstrategist, @CapitalStructure
"""

# ============== GROK SCANNER ==============

def scan_twitter_with_grok(companies: list, api_key: str) -> dict:
    """
    Ask Grok to scan Twitter for mentions of companies from credible accounts
    Returns structured findings
    """
    if not api_key or api_key == "YOUR_XAI_API_KEY":
        return None

    companies_str = ", ".join(companies)

    prompt = f"""You are a credit analyst scanning Twitter/X for alpha on high-yield bonds.

Search Twitter for recent posts (last 2 hours) mentioning ANY of these companies:
{companies_str}

Focus on posts from credible financial accounts like:
{PRIORITY_ACCOUNTS}

Also look for posts from accounts that:
- Have been active for 2+ years (not new/bot accounts)
- Have high follower/following ratio
- Get engagement from known finance accounts
- Post original analysis (not just retweets)

For each relevant finding, provide:
1. Company name mentioned
2. Twitter handle who posted
3. Key point/news (1-2 sentences)
4. Sentiment (BULLISH/BEARISH/NEUTRAL)
5. Urgency (HIGH/MEDIUM/LOW) - HIGH if breaking news or significant event

Format each finding as:
COMPANY: [name]
ACCOUNT: @[handle]
NEWS: [summary]
SENTIMENT: [BULLISH/BEARISH/NEUTRAL]
URGENCY: [HIGH/MEDIUM/LOW]
---

If you find nothing relevant in the last 2 hours, respond with: NO_ALPHA_FOUND

Only include posts that could be market-moving or provide genuine insight. Skip routine news."""

    try:
        url = "https://api.x.ai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "grok-4-1-fast-reasoning",  # Fast, cheap, 2M context
            "messages": [
                {
                    "role": "system",
                    "content": "You are a credit analyst with real-time Twitter access. Find actionable alpha for high-yield bond traders. Be specific and cite sources. Only report genuinely interesting findings."
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2  # Low temperature for factual responses
        }

        response = requests.post(url, headers=headers, json=payload, timeout=60)

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return parse_grok_findings(content)
        else:
            print(f"Grok API error: {response.status_code} - {response.text[:200]}")
            return None

    except Exception as e:
        print(f"Grok scan error: {e}")
        return None


def parse_grok_findings(content: str) -> dict:
    """Parse Grok's response into structured findings"""
    if "NO_ALPHA_FOUND" in content:
        return {"findings": [], "raw": content}

    findings = []
    current = {}

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("COMPANY:"):
            if current:
                findings.append(current)
            current = {"company": line.replace("COMPANY:", "").strip()}
        elif line.startswith("ACCOUNT:"):
            current["account"] = line.replace("ACCOUNT:", "").strip()
        elif line.startswith("NEWS:"):
            current["news"] = line.replace("NEWS:", "").strip()
        elif line.startswith("SENTIMENT:"):
            current["sentiment"] = line.replace("SENTIMENT:", "").strip()
        elif line.startswith("URGENCY:"):
            current["urgency"] = line.replace("URGENCY:", "").strip()
        elif line == "---":
            if current and current.get("company"):
                findings.append(current)
            current = {}

    if current and current.get("company"):
        findings.append(current)

    return {"findings": findings, "raw": content}


# ============== TELEGRAM ALERTS ==============

def send_telegram_alert(finding: dict) -> bool:
    """Send a finding to Telegram"""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print(f"[TELEGRAM MOCK] {finding}")
        return False

    # Format message
    sentiment_emoji = {
        "BULLISH": "🟢",
        "BEARISH": "🔴",
        "NEUTRAL": "⚪"
    }.get(finding.get("sentiment", ""), "⚪")

    urgency_emoji = {
        "HIGH": "🚨",
        "MEDIUM": "⚠️",
        "LOW": "📌"
    }.get(finding.get("urgency", ""), "📌")

    message = f"""
{urgency_emoji} <b>Twitter Alpha Alert</b> {sentiment_emoji}

<b>Company:</b> {finding.get('company', 'Unknown')}
<b>Source:</b> {finding.get('account', 'Unknown')}
<b>Sentiment:</b> {finding.get('sentiment', 'Unknown')}

<b>News:</b> {finding.get('news', 'No details')}

<i>Time: {datetime.now().strftime('%H:%M:%S')}</i>
"""

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message.strip(),
            "parse_mode": "HTML"
        }, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


# ============== DEDUPLICATION ==============

# Keep track of sent alerts to avoid duplicates
sent_alerts_file = Path(__file__).parent / "data" / "sent_twitter_alerts.json"

def load_sent_alerts() -> set:
    """Load previously sent alert hashes"""
    try:
        if sent_alerts_file.exists():
            with open(sent_alerts_file, "r") as f:
                data = json.load(f)
                # Only keep alerts from last 24 hours
                cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
                return set(h for h, t in data.items() if t > cutoff)
    except:
        pass
    return set()


def save_sent_alerts(alerts: set):
    """Save sent alert hashes"""
    try:
        sent_alerts_file.parent.mkdir(parents=True, exist_ok=True)
        data = {h: datetime.now().isoformat() for h in alerts}
        with open(sent_alerts_file, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving alerts: {e}")


def get_alert_hash(finding: dict) -> str:
    """Generate unique hash for a finding to prevent duplicates"""
    key = f"{finding.get('company', '')}{finding.get('news', '')[:50]}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ============== MAIN SCANNER LOOP ==============

def run_scanner():
    """Main scanner loop"""
    print("=" * 60)
    print("Twitter Alpha Scanner for XO S44 Credits")
    print("=" * 60)
    print(f"Monitoring {len(XO_S44_NAMES)} companies")
    print(f"Scan interval: {SCAN_INTERVAL // 60} minutes")
    print(f"Using Grok (xAI) for Twitter search")
    print("=" * 60)

    if XAI_API_KEY == "YOUR_XAI_API_KEY":
        print("\n⚠️  xAI API key not configured!")
        print("Set XAI_API_KEY environment variable or edit this file")
        print("Get your key from: console.x.ai")
        return

    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("\n⚠️  Telegram not configured - running in test mode")
        print("Alerts will be printed to console only\n")
    else:
        send_telegram_alert({
            "company": "System",
            "account": "@ApexMonitor",
            "news": "Twitter Alpha Scanner started. Monitoring XO S44 credits for alpha.",
            "sentiment": "NEUTRAL",
            "urgency": "LOW"
        })

    sent_alerts = load_sent_alerts()
    batch_index = 0

    while True:
        try:
            # Get batch of companies to scan
            start_idx = (batch_index * BATCH_SIZE) % len(XO_S44_NAMES)
            end_idx = start_idx + BATCH_SIZE
            batch = XO_S44_NAMES[start_idx:end_idx]
            if end_idx > len(XO_S44_NAMES):
                batch += XO_S44_NAMES[:end_idx - len(XO_S44_NAMES)]

            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning batch: {', '.join(batch[:3])}...")

            # Ask Grok to scan Twitter
            results = scan_twitter_with_grok(batch, XAI_API_KEY)

            if results and results.get("findings"):
                new_count = 0
                for finding in results["findings"]:
                    alert_hash = get_alert_hash(finding)

                    if alert_hash not in sent_alerts:
                        print(f"  🔔 NEW: {finding.get('company')} - {finding.get('news', '')[:50]}...")

                        # Only send HIGH/MEDIUM urgency to Telegram
                        if finding.get("urgency") in ["HIGH", "MEDIUM"]:
                            send_telegram_alert(finding)

                        sent_alerts.add(alert_hash)
                        new_count += 1

                if new_count > 0:
                    save_sent_alerts(sent_alerts)
                    print(f"  Found {new_count} new alerts")
                else:
                    print(f"  No new alerts (filtered duplicates)")
            else:
                print(f"  No alpha found this scan")

            batch_index += 1

            # Wait for next scan
            print(f"  Next scan in {SCAN_INTERVAL // 60} minutes...")
            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n\nScanner stopped.")
            save_sent_alerts(sent_alerts)
            break
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(60)  # Wait 1 minute on error


if __name__ == "__main__":
    run_scanner()
