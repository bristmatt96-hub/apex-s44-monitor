#!/usr/bin/env python3
"""
Module 14: News Sentiment Monitor
==================================
Fetches recent company news for iTraxx Crossover constituents via Finnhub,
runs FinBERT financial sentiment analysis on headlines, and computes per-name
and per-sector sentiment signals.

Data Sources:
  - Finnhub (company_news) for headlines
  - FinBERT (ProsusAI/finbert) for financial NLP sentiment

Dependencies:
  - crossover_constituents.py (for name/ticker/sector mapping)
  - pip install finnhub-python transformers torch pandas matplotlib numpy

Usage:
  set FINNHUB_API_KEY=your_key
  python news_sentiment_monitor.py

Author: Built with Claude for European credit trading
"""

import os
import sys
import time
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

try:
    import finnhub
except ImportError:
    print("ERROR: pip install finnhub-python")
    sys.exit(1)

try:
    from transformers import pipeline as hf_pipeline
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    print("WARNING: transformers not installed. Sentiment will use fallback scoring.")

warnings.filterwarnings("ignore")

# Import crossover constituents
try:
    from analytics.crossover_constituents import CONSTITUENTS
except ImportError:
    print("ERROR: crossover_constituents.py not found")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NEWS_DAYS = 7
FINNHUB_RATE_DELAY = 1.1  # seconds between API calls (60/min limit)
FINBERT_BATCH_SIZE = 32
FINBERT_MODEL = "ProsusAI/finbert"

# Yahoo ticker suffix -> Finnhub exchange mapping
EXCHANGE_MAP = {
    "PA": "PA",   # Euronext Paris
    "MI": "MI",   # Milan
    "DE": "DE",   # XETRA
    "F":  "F",    # Frankfurt
    "MC": "MC",   # Madrid
    "AS": "AS",   # Amsterdam
    "L":  "L",    # London
    "HE": "HE",   # Helsinki
    "ST": "ST",   # Stockholm
    "CO": "CO",   # Copenhagen
    "OL": "OL",   # Oslo
    "SW": "SW",   # SIX Swiss
    "VI": "VI",   # Vienna
    "WA": "WA",   # Warsaw
    "AT": "AT",   # Athens
    "PR": "PR",   # Prague
    "N":  "",     # NYSE - no suffix needed
}

# Chart styling (match dashboard theme)
CHART_BG = "#1a1a2e"
CHART_FG = "#e0e0e0"
ACCENT_BLUE = "#4fc3f7"
ACCENT_RED = "#ef5350"
ACCENT_GREEN = "#66bb6a"
ACCENT_ORANGE = "#ffa726"
ACCENT_PURPLE = "#ab47bc"


# =============================================================================
# TICKER CONVERSION
# =============================================================================

def yahoo_to_finnhub(yahoo_ticker: str) -> str:
    """Convert Yahoo Finance ticker to Finnhub format.

    Yahoo: TIT.MI, LHA.DE, IAG.L
    Finnhub: TIT (for MI), LHA (for DE), IAG (for L)
    Actually Finnhub often just uses the base symbol for company_news.
    """
    if "." in yahoo_ticker:
        base = yahoo_ticker.rsplit(".", 1)[0]
        # Handle special cases like ERIC-B.ST -> ERIC-B
        return base
    return yahoo_ticker


# =============================================================================
# DATA FETCHING
# =============================================================================

def init_finbert():
    """Initialize FinBERT sentiment pipeline. Downloads model on first run (~400MB)."""
    if not HAS_TRANSFORMERS:
        return None
    try:
        print("  Loading FinBERT model (first run downloads ~400MB)...")
        pipe = hf_pipeline("sentiment-analysis", model=FINBERT_MODEL,
                          truncation=True, max_length=512)
        print("  FinBERT loaded OK")
        return pipe
    except Exception as e:
        print(f"  WARNING: FinBERT load failed: {e}")
        return None


def fetch_company_news(client, ticker: str, days: int = DEFAULT_NEWS_DAYS) -> List[dict]:
    """Fetch recent news for a single company from Finnhub."""
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        news = client.company_news(
            ticker,
            _from=start.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d")
        )
        if news and isinstance(news, list):
            # Filter to relevant news (has headline)
            return [n for n in news if n.get("headline")]
        return []
    except Exception:
        return []


def fetch_all_news(api_key: str, days: int = DEFAULT_NEWS_DAYS) -> Dict[str, List[dict]]:
    """Fetch news for all Crossover constituents. Rate-limited."""
    client = finnhub.Client(api_key=api_key)
    all_news = {}
    total = len(CONSTITUENTS)

    print(f"\n  Fetching news for {total} names ({days} days lookback)...")
    print(f"  Rate limit: {FINNHUB_RATE_DELAY}s delay (~{int(total * FINNHUB_RATE_DELAY)}s total)")

    for i, (name, info) in enumerate(CONSTITUENTS.items(), 1):
        ticker = yahoo_to_finnhub(info["ticker"])
        news = fetch_company_news(client, ticker, days)
        if news:
            all_news[name] = news
        if i % 10 == 0 or i == total:
            n_with = len(all_news)
            total_articles = sum(len(v) for v in all_news.values())
            print(f"    [{i:02d}/{total}] {n_with} names with news, {total_articles} articles total")
        time.sleep(FINNHUB_RATE_DELAY)

    print(f"  -> {len(all_news)}/{total} names have news articles")
    return all_news


# =============================================================================
# SENTIMENT CLASSIFICATION
# =============================================================================

def classify_headlines_finbert(headlines: List[str], pipe) -> List[dict]:
    """Classify headlines using FinBERT. Returns list of {headline, label, score, numeric}."""
    results = []
    # Process in batches
    for i in range(0, len(headlines), FINBERT_BATCH_SIZE):
        batch = headlines[i:i + FINBERT_BATCH_SIZE]
        try:
            preds = pipe(batch)
            for headline, pred in zip(batch, preds):
                label = pred["label"].lower()
                score = pred["score"]
                # Convert to numeric: positive=+1, negative=-1, neutral=0
                if label == "positive":
                    numeric = score
                elif label == "negative":
                    numeric = -score
                else:
                    numeric = 0.0
                results.append({
                    "headline": headline[:100],
                    "label": label,
                    "score": round(score, 3),
                    "numeric": round(numeric, 3),
                })
        except Exception:
            # Fallback for failed batches
            for headline in batch:
                results.append({
                    "headline": headline[:100],
                    "label": "neutral",
                    "score": 0.5,
                    "numeric": 0.0,
                })
    return results


def classify_headlines_fallback(headlines: List[str]) -> List[dict]:
    """Simple keyword-based fallback when FinBERT is not available."""
    negative_words = {"loss", "decline", "downgrade", "cut", "miss", "weak", "fall",
                      "drop", "risk", "default", "debt", "bankruptcy", "layoff",
                      "restructuring", "warning", "concern", "slump", "crisis",
                      "downturn", "recession", "lawsuit", "fraud", "probe"}
    positive_words = {"profit", "growth", "upgrade", "beat", "strong", "rise",
                      "gain", "rally", "recovery", "dividend", "expansion",
                      "acquisition", "deal", "outlook", "record", "surpass",
                      "boost", "upbeat", "improve", "optimis"}
    results = []
    for headline in headlines:
        words = set(headline.lower().split())
        neg_count = len(words & negative_words)
        pos_count = len(words & positive_words)
        if neg_count > pos_count:
            label, score, numeric = "negative", 0.6, -0.6
        elif pos_count > neg_count:
            label, score, numeric = "positive", 0.6, 0.6
        else:
            label, score, numeric = "neutral", 0.5, 0.0
        results.append({
            "headline": headline[:100],
            "label": label,
            "score": round(score, 3),
            "numeric": round(numeric, 3),
        })
    return results


def classify_headlines(headlines: List[str], pipe) -> List[dict]:
    """Classify headlines using FinBERT or fallback."""
    if pipe is not None:
        return classify_headlines_finbert(headlines, pipe)
    else:
        return classify_headlines_fallback(headlines)


# =============================================================================
# SENTIMENT COMPUTATION
# =============================================================================

def compute_name_sentiment(name: str, news: List[dict], classified: List[dict],
                            days: int = DEFAULT_NEWS_DAYS) -> dict:
    """Compute sentiment metrics for a single name."""
    if not classified:
        return {
            "name": name,
            "n_articles": 0,
            "avg_sentiment": 0.0,
            "pct_negative": 0.0,
            "pct_positive": 0.0,
            "pct_neutral": 0.0,
            "sentiment_momentum": 0.0,
            "composite_signal": 0.0,
        }

    numerics = [c["numeric"] for c in classified]
    labels = [c["label"] for c in classified]
    n = len(classified)

    avg_sent = np.mean(numerics)
    pct_neg = sum(1 for l in labels if l == "negative") / n
    pct_pos = sum(1 for l in labels if l == "positive") / n
    pct_neu = sum(1 for l in labels if l == "neutral") / n

    # Momentum: recent (last 3 days) vs older (prior days)
    # Use article timestamps if available
    recent_cutoff = datetime.now() - timedelta(days=days // 2)
    recent_nums = []
    older_nums = []
    for article, cl in zip(news[:len(classified)], classified):
        ts = article.get("datetime", 0)
        if ts > 0:
            dt = datetime.fromtimestamp(ts)
            if dt >= recent_cutoff:
                recent_nums.append(cl["numeric"])
            else:
                older_nums.append(cl["numeric"])
        else:
            recent_nums.append(cl["numeric"])

    if recent_nums and older_nums:
        momentum = np.mean(recent_nums) - np.mean(older_nums)
    else:
        momentum = 0.0

    # Composite signal: weighted combination
    # 50% avg sentiment + 30% negative pct (inverted) + 20% momentum
    composite = avg_sent * 0.5 + (-pct_neg + pct_pos) * 0.3 + momentum * 0.2
    # Clip to [-2, +2]
    composite = np.clip(composite * 2, -2, 2)

    return {
        "name": name,
        "n_articles": n,
        "avg_sentiment": round(avg_sent, 3),
        "pct_negative": round(pct_neg * 100, 1),
        "pct_positive": round(pct_pos * 100, 1),
        "pct_neutral": round(pct_neu * 100, 1),
        "sentiment_momentum": round(momentum, 3),
        "composite_signal": round(composite, 2),
    }


def compute_all_sentiment(all_news: Dict[str, List[dict]], pipe) -> pd.DataFrame:
    """Compute sentiment for all names with news."""
    print("\n  Computing sentiment scores...")
    rows = []
    total_articles = sum(len(v) for v in all_news.values())
    print(f"  Total articles to classify: {total_articles}")

    for name, news in all_news.items():
        headlines = [n.get("headline", "") for n in news if n.get("headline")]
        if not headlines:
            continue
        classified = classify_headlines(headlines, pipe)
        info = CONSTITUENTS.get(name, {})
        metrics = compute_name_sentiment(name, news, classified)
        metrics["ticker"] = info.get("ticker", "")
        metrics["sector"] = info.get("sector", "")
        metrics["rating"] = info.get("rating", "")
        metrics["country"] = info.get("country", "")
        rows.append(metrics)

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("composite_signal", ascending=True)
    print(f"  -> {len(df)} names with sentiment scores")
    return df


def sector_sentiment_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sentiment by sector."""
    if len(df) == 0:
        return pd.DataFrame()

    sector_rows = []
    for sector in sorted(df["sector"].unique()):
        sub = df[df["sector"] == sector]
        sector_rows.append({
            "sector": sector,
            "n_names": len(sub),
            "avg_sentiment": round(sub["avg_sentiment"].mean(), 3),
            "avg_pct_negative": round(sub["pct_negative"].mean(), 1),
            "avg_pct_positive": round(sub["pct_positive"].mean(), 1),
            "avg_momentum": round(sub["sentiment_momentum"].mean(), 3),
            "avg_signal": round(sub["composite_signal"].mean(), 2),
            "total_articles": sub["n_articles"].sum(),
        })

    return pd.DataFrame(sector_rows).sort_values("avg_signal", ascending=True)


def flag_sentiment_shifts(df: pd.DataFrame) -> pd.DataFrame:
    """Flag names with sharp negative sentiment shifts."""
    if len(df) == 0:
        return pd.DataFrame()

    flagged = df[
        (df["sentiment_momentum"] < -0.15) &
        (df["avg_sentiment"] < 0.0)
    ].copy()

    if len(flagged) > 0:
        flagged = flagged.sort_values("sentiment_momentum", ascending=True)
    return flagged


# =============================================================================
# CONSOLE REPORT
# =============================================================================

def print_report(df: pd.DataFrame, sector_df: pd.DataFrame,
                  flagged_df: pd.DataFrame, all_news: Dict):
    """Print sentiment analysis report."""
    w = 100
    print("\n" + "=" * w)
    print("  NEWS SENTIMENT MONITOR - iTRAXX CROSSOVER CONSTITUENTS")
    print("=" * w)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    total_articles = sum(len(v) for v in all_news.values())
    print(f"  Names with news: {len(df)} / {len(CONSTITUENTS)}")
    print(f"  Total articles: {total_articles}")

    # 1. OVERVIEW
    print("\n" + "=" * w)
    print("  1. SENTIMENT OVERVIEW")
    print("=" * w)
    if len(df) > 0:
        avg = df["avg_sentiment"].mean()
        n_neg = len(df[df["avg_sentiment"] < -0.1])
        n_pos = len(df[df["avg_sentiment"] > 0.1])
        n_neu = len(df) - n_neg - n_pos
        regime = "BEARISH" if avg < -0.15 else "BULLISH" if avg > 0.15 else "NEUTRAL"
        print(f"  Average Sentiment:  {avg:+.3f}  [{regime}]")
        print(f"  Distribution:       {n_neg} negative / {n_neu} neutral / {n_pos} positive")
        print(f"  Avg Pct Negative:   {df['pct_negative'].mean():.1f}%")
        print(f"  Avg Pct Positive:   {df['pct_positive'].mean():.1f}%")

    # 2. FULL RANKING
    print("\n" + "=" * w)
    print("  2. FULL SENTIMENT RANKING (most negative first)")
    print("=" * w)
    if len(df) > 0:
        print(f"  {'Name':<28s} {'Sector':<14s} {'Avg Sent':>9s} {'%Neg':>6s} {'%Pos':>6s} {'Mom':>7s} {'Signal':>7s} {'#Art':>5s}")
        print("  " + "-" * 90)
        for _, row in df.iterrows():
            sig = row["composite_signal"]
            marker = " !!" if sig <= -1.0 else " !" if sig <= -0.5 else ""
            print(f"  {row['name']:<28s} {row['sector']:<14s} {row['avg_sentiment']:+.3f}"
                  f"  {row['pct_negative']:>5.1f} {row['pct_positive']:>5.1f}"
                  f"  {row['sentiment_momentum']:+.3f} {sig:+.2f}{marker}"
                  f"  {row['n_articles']:>4d}")

    # 3. TOP 5 NEGATIVE
    print("\n" + "=" * w)
    print("  3. TOP 5 MOST NEGATIVE (protection candidates)")
    print("=" * w)
    if len(df) >= 1:
        for _, row in df.head(5).iterrows():
            print(f"  {row['name']:<28s} signal={row['composite_signal']:+.2f}"
                  f"  avg_sent={row['avg_sentiment']:+.3f}"
                  f"  %neg={row['pct_negative']:.0f}%  mom={row['sentiment_momentum']:+.3f}")

    # 4. TOP 5 POSITIVE
    print("\n" + "=" * w)
    print("  4. TOP 5 MOST POSITIVE")
    print("=" * w)
    if len(df) >= 1:
        for _, row in df.tail(5).iloc[::-1].iterrows():
            print(f"  {row['name']:<28s} signal={row['composite_signal']:+.2f}"
                  f"  avg_sent={row['avg_sentiment']:+.3f}"
                  f"  %pos={row['pct_positive']:.0f}%  mom={row['sentiment_momentum']:+.3f}")

    # 5. SECTOR SUMMARY
    print("\n" + "=" * w)
    print("  5. SECTOR SENTIMENT SUMMARY")
    print("=" * w)
    if len(sector_df) > 0:
        print(f"  {'Sector':<18s} {'#Names':>6s} {'Avg Sent':>9s} {'%Neg':>6s} {'%Pos':>6s} {'Mom':>7s} {'Signal':>7s} {'#Art':>5s}")
        print("  " + "-" * 75)
        for _, row in sector_df.iterrows():
            print(f"  {row['sector']:<18s} {row['n_names']:>5d}"
                  f"  {row['avg_sentiment']:+.3f} {row['avg_pct_negative']:>5.1f}"
                  f"  {row['avg_pct_positive']:>5.1f} {row['avg_momentum']:+.3f}"
                  f"  {row['avg_signal']:+.2f} {row['total_articles']:>4d}")

    # 6. FLAGGED
    print("\n" + "=" * w)
    print("  6. FLAGGED: SHARP NEGATIVE SHIFTS")
    print("=" * w)
    if len(flagged_df) > 0:
        for _, row in flagged_df.iterrows():
            print(f"  ** {row['name']:<26s} momentum={row['sentiment_momentum']:+.3f}"
                  f"  avg={row['avg_sentiment']:+.3f}  signal={row['composite_signal']:+.2f}")
    else:
        print("  No sharp negative shifts detected")

    # 7. IMPLICATIONS
    print("\n" + "=" * w)
    print("  7. iTRAXX CROSSOVER IMPLICATIONS")
    print("=" * w)
    if len(df) > 0:
        avg = df["avg_sentiment"].mean()
        n_flagged = len(flagged_df)
        if avg < -0.15:
            print("  -> BEARISH SENTIMENT: Broad negative news flow across Crossover names")
            print("     Consider: Increase short exposure, buy protection on weakest names")
        elif avg > 0.15:
            print("  -> BULLISH SENTIMENT: Positive news flow supports credit")
            print("     Consider: Lean long, look for spread compression in strongest names")
        else:
            print("  -> MIXED SENTIMENT: No strong directional bias from news flow")

        if n_flagged > 3:
            print(f"  -> WARNING: {n_flagged} names with sharp negative shifts")
            print("     Potential catalyst for wider spread moves if confirmed by fundamentals")

    print("\n" + "=" * w)


# =============================================================================
# VISUALIZATION
# =============================================================================

def plot_dashboard(df: pd.DataFrame, sector_df: pd.DataFrame,
                    flagged_df: pd.DataFrame, all_news: Dict):
    """Create 6-panel news sentiment dashboard."""
    fig = plt.figure(figsize=(24, 18))
    fig.patch.set_facecolor(CHART_BG)
    gs = gridspec.GridSpec(3, 3, hspace=0.35, wspace=0.25,
                           left=0.06, right=0.96, top=0.93, bottom=0.05)

    fig.suptitle("NEWS SENTIMENT MONITOR - CROSSOVER CONSTITUENTS",
                 color=ACCENT_BLUE, fontsize=18, fontweight="bold", y=0.97,
                 fontfamily="monospace")

    # --- Panel 1: Sentiment bar chart (all names sorted) ---
    ax1 = fig.add_subplot(gs[0, :2])
    ax1.set_facecolor(CHART_BG)
    ax1.set_title("Sentiment by Name (sorted)", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        display = df.head(40)  # Show top 40
        names = display["name"].tolist()
        vals = display["avg_sentiment"].tolist()
        bar_colors = [ACCENT_RED if v < -0.1 else ACCENT_GREEN if v > 0.1 else CHART_FG for v in vals]
        y_pos = range(len(names))
        ax1.barh(y_pos, vals, color=bar_colors, alpha=0.7, height=0.7)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels([n[:20] for n in names], fontsize=6, color=CHART_FG)
        ax1.axvline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
        ax1.set_xlabel("Avg Sentiment (-1 to +1)", color=CHART_FG, fontsize=8)
        ax1.invert_yaxis()

    ax1.tick_params(colors=CHART_FG, labelsize=7)
    for spine in ax1.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 2: Summary box ---
    ax2 = fig.add_subplot(gs[0, 2])
    ax2.set_facecolor(CHART_BG)
    ax2.axis("off")
    ax2.set_title("Summary", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        avg = df["avg_sentiment"].mean()
        regime = "BEARISH" if avg < -0.15 else "BULLISH" if avg > 0.15 else "NEUTRAL"
        regime_color = ACCENT_RED if avg < -0.15 else ACCENT_GREEN if avg > 0.15 else ACCENT_ORANGE
        total_art = sum(len(v) for v in all_news.values())
        n_neg = len(df[df["avg_sentiment"] < -0.1])
        n_pos = len(df[df["avg_sentiment"] > 0.1])

        lines = [
            f"Sentiment Regime: {regime}",
            f"Avg Sentiment: {avg:+.3f}",
            f"",
            f"Names with News: {len(df)}/{len(CONSTITUENTS)}",
            f"Total Articles: {total_art}",
            f"",
            f"Negative Names: {n_neg}",
            f"Positive Names: {n_pos}",
            f"Flagged Shifts: {len(flagged_df)}",
        ]
        for i, line in enumerate(lines):
            color = regime_color if i == 0 else CHART_FG
            ax2.text(0.05, 0.92 - i * 0.10, line, transform=ax2.transAxes,
                    fontsize=11, color=color, fontfamily="monospace", va="top")

    # --- Panel 3: Sector heatmap ---
    ax3 = fig.add_subplot(gs[1, :2])
    ax3.set_facecolor(CHART_BG)
    ax3.set_title("Sector Sentiment Summary", color=CHART_FG, fontsize=11)

    if len(sector_df) > 0:
        sectors = sector_df["sector"].tolist()
        metrics = ["avg_sentiment", "avg_pct_negative", "avg_momentum", "avg_signal"]
        metric_labels = ["Avg Sent", "% Neg", "Momentum", "Signal"]

        heatmap_data = np.zeros((len(sectors), len(metrics)))
        for i, (_, row) in enumerate(sector_df.iterrows()):
            for j, m in enumerate(metrics):
                val = row.get(m, 0)
                # Normalize for display
                if m == "avg_pct_negative":
                    heatmap_data[i, j] = val / 50  # normalize 0-100 to 0-2 range
                else:
                    heatmap_data[i, j] = val

        im = ax3.imshow(heatmap_data, aspect="auto", cmap="RdYlGn", vmin=-1, vmax=1)
        ax3.set_xticks(range(len(metrics)))
        ax3.set_xticklabels(metric_labels, fontsize=9, color=CHART_FG)
        ax3.set_yticks(range(len(sectors)))
        ax3.set_yticklabels(sectors, fontsize=8, color=CHART_FG)

        for i in range(len(sectors)):
            for j, m in enumerate(metrics):
                val = sector_df.iloc[i][m]
                fmt = f"{val:+.2f}" if m != "avg_pct_negative" else f"{val:.0f}%"
                ax3.text(j, i, fmt, ha="center", va="center",
                        color="white" if abs(heatmap_data[i, j]) > 0.5 else CHART_FG,
                        fontsize=8)

    ax3.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax3.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 4: Sentiment distribution histogram ---
    ax4 = fig.add_subplot(gs[1, 2])
    ax4.set_facecolor(CHART_BG)
    ax4.set_title("Sentiment Distribution", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        vals = df["avg_sentiment"].values
        bins = np.linspace(-1, 1, 21)
        n_vals, _, patches = ax4.hist(vals, bins=bins, alpha=0.7, edgecolor="none")
        for patch, left in zip(patches, bins[:-1]):
            mid = left + 0.05
            if mid < -0.1:
                patch.set_facecolor(ACCENT_RED)
            elif mid > 0.1:
                patch.set_facecolor(ACCENT_GREEN)
            else:
                patch.set_facecolor(CHART_FG)
            patch.set_alpha(0.7)
        ax4.axvline(0, color=CHART_FG, linewidth=0.5, alpha=0.5)
        ax4.set_xlabel("Avg Sentiment", color=CHART_FG, fontsize=8)
        ax4.set_ylabel("Count", color=CHART_FG, fontsize=8)

    ax4.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax4.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # --- Panel 5: Top 10 most negative ---
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.set_facecolor(CHART_BG)
    ax5.axis("off")
    ax5.set_title("Top 10 Most Negative", color=ACCENT_RED, fontsize=11)

    if len(df) >= 1:
        top_neg = df.head(10)
        for i, (_, row) in enumerate(top_neg.iterrows()):
            color = ACCENT_RED if row["composite_signal"] <= -0.5 else CHART_FG
            line = f"{row['name'][:22]:<22s} sig={row['composite_signal']:+.1f} %neg={row['pct_negative']:.0f}%"
            ax5.text(0.02, 0.92 - i * 0.09, line, transform=ax5.transAxes,
                    fontsize=9, color=color, fontfamily="monospace", va="top")

    # --- Panel 6: Momentum vs sentiment scatter ---
    ax6 = fig.add_subplot(gs[2, 1:])
    ax6.set_facecolor(CHART_BG)
    ax6.set_title("Sentiment vs Momentum (flagged in red)", color=CHART_FG, fontsize=11)

    if len(df) > 0:
        x = df["avg_sentiment"].values
        y = df["sentiment_momentum"].values
        is_flagged = df.index.isin(flagged_df.index) if len(flagged_df) > 0 else [False] * len(df)

        normal = ~np.array(list(is_flagged))
        ax6.scatter(x[normal], y[normal], color=ACCENT_BLUE, alpha=0.5, s=30, label="Normal")
        if any(is_flagged):
            flagged_mask = np.array(list(is_flagged))
            ax6.scatter(x[flagged_mask], y[flagged_mask], color=ACCENT_RED, alpha=0.8,
                       s=60, marker="x", linewidths=2, label="Flagged")

        ax6.axhline(0, color=CHART_FG, linewidth=0.5, alpha=0.3)
        ax6.axvline(0, color=CHART_FG, linewidth=0.5, alpha=0.3)
        ax6.set_xlabel("Avg Sentiment", color=CHART_FG, fontsize=8)
        ax6.set_ylabel("Momentum", color=CHART_FG, fontsize=8)
        ax6.legend(fontsize=8, facecolor=CHART_BG, edgecolor=CHART_FG, labelcolor=CHART_FG)

    ax6.tick_params(colors=CHART_FG, labelsize=8)
    for spine in ax6.spines.values():
        spine.set_color(CHART_FG)
        spine.set_alpha(0.3)

    # Save
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "news_sentiment_dashboard.png")
    plt.savefig(out_path, dpi=150, facecolor=CHART_BG, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Chart saved: news_sentiment_dashboard.png")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run News Sentiment Monitor pipeline."""
    w = 80
    print("\n" + "=" * w)
    print("  MODULE 14: NEWS SENTIMENT MONITOR")
    print("  Finnhub News + FinBERT Sentiment for Crossover Constituents")
    print("=" * w)
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check API key
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        print("\n  ERROR: FINNHUB_API_KEY not set")
        print("  Set via: set FINNHUB_API_KEY=your_key")
        print("  Get free key: https://finnhub.io/register")
        return

    # 1. Initialize FinBERT
    print("\n  Step 1: Initializing sentiment model...")
    pipe = init_finbert()

    # 2. Fetch news
    print("\n  Step 2: Fetching company news from Finnhub...")
    all_news = fetch_all_news(api_key, days=DEFAULT_NEWS_DAYS)

    if not all_news:
        print("  ERROR: No news fetched. Check API key and network.")
        return

    # 3. Compute sentiment
    print("\n  Step 3: Computing sentiment scores...")
    df = compute_all_sentiment(all_news, pipe)

    if len(df) == 0:
        print("  ERROR: No sentiment data computed")
        return

    # 4. Sector summary
    print("\n  Step 4: Computing sector summaries...")
    sector_df = sector_sentiment_summary(df)

    # 5. Flag shifts
    print("\n  Step 5: Flagging negative sentiment shifts...")
    flagged_df = flag_sentiment_shifts(df)
    print(f"  -> {len(flagged_df)} names flagged")

    # 6. Report
    print_report(df, sector_df, flagged_df, all_news)

    # 7. Chart
    print("\n  Step 7: Generating dashboard chart...")
    plot_dashboard(df, sector_df, flagged_df, all_news)

    # 8. CSV
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "news_sentiment.csv")
    df.to_csv(csv_path, index=False)
    print(f"  CSV saved: news_sentiment.csv")

    print("\n  DONE.")


if __name__ == "__main__":
    main()
