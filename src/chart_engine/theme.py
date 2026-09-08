from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

PAPER = "#FAF5EA"        
INK = "#232F35"         
INK_SOFT = "#5B6B72"     
GRID = "#DCD1BC"         
COPPER = "#B07A16"       
INDIGO = "#1E6E9E"      
PLUM = "#A8447A"       
COPPER_FILL = "#E3C079"
INDIGO_FILL = "#84B6D2"
MOSS = "#4B6A5E"        
VERMILION = "#C4291C" 
SAND = "#EFE4CC"

SERIES_COLORS = [COPPER, INDIGO, PLUM]
MAX_SERIES = len(SERIES_COLORS)

SERIES_DASHES = ["solid", (0, (6, 2.5)), (0, (1.5, 1.8))]


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": GRID,
            "axes.titlecolor": INK,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "grid.alpha": 0.9,
            "xtick.color": INK_SOFT,
            "ytick.color": INK_SOFT,
            "legend.frameon": False,
            "figure.dpi": 110,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def strip_frame(ax, keep=("left", "bottom")) -> None:
    """Drop the spines that carry no information."""
    for side, spine in ax.spines.items():
        spine.set_visible(side in keep)
