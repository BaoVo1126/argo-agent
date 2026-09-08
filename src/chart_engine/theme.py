"""
Palette and matplotlib styling for every chart Argo renders.

One place, because a chart that ships in the report and a chart that ships in
the web UI have to look like the same product. The colours come from the
project style guide (paper, ink, copper, moss, vermilion) read through a
Japanese landscape: washi paper ground, sumi ink text, a copper-gold and an
indigo series that stay distinguishable when the figure is printed grey.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # no display on this machine, and none needed for a PNG

import matplotlib.pyplot as plt

# --- Named colours -------------------------------------------------------
PAPER = "#FAF5EA"        # kinari / nen giay -- figure and axes ground
INK = "#232F35"          # sumi -- titles and axis labels
INK_SOFT = "#5B6B72"     # secondary text, tick labels
GRID = "#DCD1BC"         # faint rule, meant to sit under the data
COPPER = "#B07A16"       # yamabuki -- series 1
INDIGO = "#1E6E9E"       # ai-iro -- series 2
PLUM = "#A8447A"         # ume -- series 3
COPPER_FILL = "#E3C079"
INDIGO_FILL = "#84B6D2"
MOSS = "#4B6A5E"         # xanh reu -- decoration only, never a data series
VERMILION = "#C4291C"    # shu-iro -- annotations only, never a data series
SAND = "#EFE4CC"

# The categorical order, assigned in this sequence and never cycled.
#
# These three were not chosen by eye. They are the result of running the
# palette through `scripts/validate_palette.js` against the #FAF5EA ground
# with `--pairs all`, which is what turns "these look different to me" into a
# measurement. The first attempt -- a deeper kon blue and a moss green -- read
# as grey to the validator (chroma below floor) and put copper and moss 3.1
# apart under protanopia, which is invisible. This set passes the lightness
# band, the chroma floor, the normal-vision floor and contrast; the CVD check
# comes back WARN at 7.0 for indigo/plum, which the reference calls legal only
# alongside a second, non-colour encoding. Hence SERIES_DASHES.
#
# Three is the whole list on purpose. A fourth hue that stays clear of these
# three on the all-pairs check does not exist in this range, and inventing one
# anyway is how a chart ends up with two series nobody can tell apart. A
# dataset with four series wants small multiples, not a fourth colour.
SERIES_COLORS = [COPPER, INDIGO, PLUM]
MAX_SERIES = len(SERIES_COLORS)

# The second encoding the CVD warning requires: line style, which survives
# colour blindness, greyscale printing and forced-colours mode alike.
SERIES_DASHES = ["solid", (0, (6, 2.5)), (0, (1.5, 1.8))]


def apply_style() -> None:
    """Global rcParams. Called once by the renderer, not at import time."""
    plt.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            # DejaVu Sans is matplotlib's bundled default and covers Vietnamese
            # diacritics; naming a font the machine lacks costs a warning per
            # glyph and silently falls back anyway.
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
