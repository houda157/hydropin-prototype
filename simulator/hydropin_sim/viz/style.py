"""One visual identity for every HydroPin figure.

Palette: validated categorical order (blue, orange, aqua, yellow, ...), checked
with the data-viz validator (CVD-safe adjacent pairs, light surface). Rules:
thin 2 px lines, >= 8 px markers with a surface ring, hairline solid grid,
text in text colours (never the series colour), legend for >= 2 series plus
direct labels at line ends, one y-axis per panel.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e6e5e0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = ["#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f2a3a3", "#e34948", "#a32a2a"]
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
BAND = "#f0efec"   # neutral wash for regime bands

LINE_W = 1.5       # points (= 2 px at 96 dpi)
MARKER = 6.5       # points (>= 8 px)

SEQ_CMAP = LinearSegmentedColormap.from_list("hp_seq", SEQ_BLUE)
DIV_CMAP = LinearSegmentedColormap.from_list("hp_div", DIVERGING)


def apply() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "figure.dpi": 110,
        "savefig.dpi": 170,
        "font.family": "DejaVu Sans",
        "font.size": 9.5,
        "axes.titlesize": 11.5,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 22,
        "axes.labelsize": 9.5,
        "axes.labelcolor": TEXT_2,
        "axes.edgecolor": GRID,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "xtick.color": TEXT_2,
        "ytick.color": TEXT_2,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "xtick.minor.size": 0,
        "ytick.minor.size": 0,
        "text.color": TEXT,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "legend.labelcolor": TEXT_2,
        "lines.linewidth": LINE_W,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "lines.markersize": MARKER,
        "axes.prop_cycle": plt.cycler(color=SERIES),
    })


def figure(nrows=1, ncols=1, w=7.6, h=4.3, **kw):
    apply()
    fig, ax = plt.subplots(nrows, ncols, figsize=(w, h), constrained_layout=True, **kw)
    return fig, ax


def subtitle(ax, text: str) -> None:
    """Grey one-line subtitle under the bold left-aligned title."""
    ax.text(0, 1.018, text, transform=ax.transAxes, fontsize=8.8, color=TEXT_2,
            va="bottom", ha="left")


def end_label(ax, x, y, text, dx=6, dy=0, ha="left", va="center") -> None:
    """Direct label at a line end, in text colour (identity comes from the mark)."""
    ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points",
                fontsize=8.5, color=TEXT_2, ha=ha, va=va)


def dot(ax, x, y, color, size=MARKER, zorder=5) -> None:
    """Marker with a 2 px surface ring."""
    ax.plot([x], [y], "o", color=color, markersize=size, markeredgecolor=SURFACE,
            markeredgewidth=1.5, zorder=zorder)


def note(ax, text: str, xy=(0.02, 0.04), ha="left") -> None:
    ax.text(*xy, text, transform=ax.transAxes, fontsize=8, color=MUTED, ha=ha, va="bottom")


def save(fig, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return path
