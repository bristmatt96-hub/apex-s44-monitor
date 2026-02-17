"""
Shared chart utilities for all analytics modules.
Dark-themed matplotlib helpers matching the APEX visual style.

Includes ChartCache for TTL-based caching, stale-while-revalidate,
and background pre-computation of all analytics charts.
"""

import io
import time
import base64
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

logger = logging.getLogger(__name__)


# APEX dark theme colors
COLORS = {
    "bg": "#0a0a0a",
    "panel": "#1a1a2e",
    "grid": "#2a2a4a",
    "text": "#e0e0e0",
    "text_dim": "#888888",
    "cyan": "#00d4ff",
    "purple": "#7b2ff7",
    "green": "#00e676",
    "red": "#ff1744",
    "orange": "#ff9100",
    "yellow": "#ffea00",
    "blue": "#2979ff",
    "pink": "#f50057",
    "teal": "#1de9b6",
    "lime": "#c6ff00",
}

PALETTE = [COLORS["cyan"], COLORS["purple"], COLORS["green"],
           COLORS["orange"], COLORS["red"], COLORS["yellow"],
           COLORS["blue"], COLORS["pink"], COLORS["teal"], COLORS["lime"]]


def setup_dark_style():
    """Apply APEX dark theme to matplotlib — modern terminal aesthetic."""
    plt.rcParams.update({
        "figure.facecolor": COLORS["bg"],
        "axes.facecolor": COLORS["panel"],
        "axes.edgecolor": COLORS["grid"],
        "axes.labelcolor": COLORS["text_dim"],
        "axes.grid": True,
        "axes.linewidth": 0.4,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": COLORS["grid"],
        "grid.alpha": 0.3,
        "grid.linewidth": 0.4,
        "grid.linestyle": "--",
        "text.color": COLORS["text"],
        "xtick.color": COLORS["text_dim"],
        "ytick.color": COLORS["text_dim"],
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "xtick.major.pad": 6,
        "ytick.major.pad": 6,
        "legend.facecolor": COLORS["bg"],
        "legend.edgecolor": "none",
        "legend.framealpha": 0.6,
        "legend.fontsize": 7,
        "font.family": "monospace",
        "font.size": 9,
        "lines.linewidth": 1.5,
        "lines.antialiased": True,
        "patch.linewidth": 0,
        "savefig.pad_inches": 0.15,
    })


def fig_to_base64(fig):
    """Convert matplotlib figure to base64 PNG for embedding in HTML."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{b64}"


def make_figure(rows=2, cols=3, figsize=(18, 10), title=None):
    """Create a dark-themed figure with subplots."""
    setup_dark_style()
    fig, axes = plt.subplots(rows, cols, figsize=figsize,
                             facecolor=COLORS["bg"])
    if title:
        fig.suptitle(title, fontsize=16, fontweight="bold",
                     color=COLORS["cyan"], y=0.98)
    fig.subplots_adjust(hspace=0.35, wspace=0.3)
    return fig, axes


def style_ax(ax, title=None, xlabel=None, ylabel=None):
    """Apply consistent styling to an axis — clean terminal look."""
    if title:
        ax.set_title(title.upper(), fontsize=8, fontweight="bold",
                     color=COLORS["cyan"], pad=10, loc="left")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=7.5, color=COLORS["text_dim"],
                      labelpad=8)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=7.5, color=COLORS["text_dim"],
                      labelpad=8)
    ax.tick_params(labelsize=7, colors=COLORS["text_dim"])
    # Ensure left/bottom spines are subtle
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(COLORS["grid"])
        ax.spines[spine].set_linewidth(0.4)


# ---------------------------------------------------------------------------
# Chart cache with TTL, stale-while-revalidate, and background workers
# ---------------------------------------------------------------------------
class ChartCache:
    """
    In-memory chart cache with TTL and background refresh.

    - Fresh cache hit: return immediately (zero compute cost)
    - Stale cache hit: return stale data, refresh in background thread
    - Cache miss: compute synchronously (first request only)
    """

    def __init__(self, ttl=300, max_workers=2):
        self._cache = {}       # {name: {"data": str, "expires": float}}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="chart-worker")
        self._refreshing = set()
        self.ttl = ttl

    def get(self, name):
        """Get cached chart data, or None if not cached."""
        with self._lock:
            entry = self._cache.get(name)
            return entry["data"] if entry else None

    def is_fresh(self, name):
        """Check if cache entry is still within TTL."""
        with self._lock:
            entry = self._cache.get(name)
            return bool(entry and time.time() < entry["expires"])

    def set(self, name, data):
        """Store chart data with TTL."""
        with self._lock:
            self._cache[name] = {
                "data": data,
                "expires": time.time() + self.ttl,
            }
            self._refreshing.discard(name)

    def get_or_compute(self, name, generate_fn):
        """
        Get cached chart, computing if needed.

        - Fresh: return immediately
        - Stale: return stale data, refresh in background
        - Miss: compute synchronously (first request)
        """
        if self.is_fresh(name):
            return self.get(name)

        cached = self.get(name)
        if cached is not None:
            self._refresh_in_background(name, generate_fn)
            return cached

        # No cache — compute synchronously
        data = generate_fn()
        self.set(name, data)
        return data

    def _refresh_in_background(self, name, generate_fn):
        """Submit background refresh if not already in progress."""
        with self._lock:
            if name in self._refreshing:
                return
            self._refreshing.add(name)

        def _do_refresh():
            try:
                data = generate_fn()
                self.set(name, data)
                logger.info("Chart cache refreshed: %s", name)
            except Exception:
                logger.exception("Chart cache refresh failed: %s", name)
                with self._lock:
                    self._refreshing.discard(name)

        self._executor.submit(_do_refresh)

    def precompute_all(self, generators):
        """
        Pre-compute all charts in background threads.
        generators: dict of {name: generate_fn}
        """
        for name, fn in generators.items():
            self._executor.submit(self._precompute_one, name, fn)

    def _precompute_one(self, name, generate_fn):
        """Compute and cache a single chart."""
        try:
            data = generate_fn()
            self.set(name, data)
            logger.info("Chart pre-computed: %s", name)
        except Exception:
            logger.exception("Chart pre-computation failed: %s", name)


# Global cache instance — 5 min TTL, 2 background workers
chart_cache = ChartCache(ttl=300, max_workers=2)
