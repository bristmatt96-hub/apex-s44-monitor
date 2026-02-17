"""
Shared chart utilities for all analytics modules.
Dark-themed matplotlib helpers matching the APEX visual style.
"""

import io
import base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


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
    """Apply APEX dark theme to matplotlib."""
    plt.rcParams.update({
        "figure.facecolor": COLORS["bg"],
        "axes.facecolor": COLORS["panel"],
        "axes.edgecolor": COLORS["grid"],
        "axes.labelcolor": COLORS["text"],
        "axes.grid": True,
        "grid.color": COLORS["grid"],
        "grid.alpha": 0.5,
        "text.color": COLORS["text"],
        "xtick.color": COLORS["text_dim"],
        "ytick.color": COLORS["text_dim"],
        "legend.facecolor": COLORS["panel"],
        "legend.edgecolor": COLORS["grid"],
        "font.family": "sans-serif",
        "font.size": 10,
    })


def fig_to_base64(fig):
    """Convert matplotlib figure to base64 PNG for embedding in HTML."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
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
    """Apply consistent styling to an axis."""
    if title:
        ax.set_title(title, fontsize=11, fontweight="bold",
                     color=COLORS["text"], pad=8)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(labelsize=8)
