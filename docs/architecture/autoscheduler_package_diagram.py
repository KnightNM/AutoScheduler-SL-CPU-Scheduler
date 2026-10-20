"""Render a black-and-white UML-style package diagram for AutoScheduler."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/autoscheduler-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/autoscheduler-cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

try:
    import seaborn as sns
except ModuleNotFoundError:
    sns = None


INK = "#000000"
PAPER = "#ffffff"


def package(ax, x, y, width, height, title, lines=(), *, tab_width=None, font_size=7.2):
    """Draw a UML package body and its title tab."""
    tab_width = tab_width or min(width * 0.72, max(118, 18 + len(title) * 7.0))
    tab_height = 28
    ax.add_patch(Rectangle((x, y), width, height, facecolor=PAPER, edgecolor=INK, linewidth=1.2, zorder=2))
    ax.add_patch(
        Rectangle((x, y - tab_height), tab_width, tab_height, facecolor=PAPER, edgecolor=INK, linewidth=1.2, zorder=3)
    )
    ax.text(x + 10, y - 9, title, fontsize=8.1, fontweight="bold", va="center", color=INK, zorder=4)
    for index, line in enumerate(lines):
        ax.text(
            x + 12,
            y + 28 + index * 20,
            f"+ {line}",
            fontsize=font_size,
            family="DejaVu Sans Mono" if line.endswith(('.py', '.json', '/')) else "DejaVu Sans",
            color=INK,
            va="center",
            zorder=4,
        )


def dependency(ax, points, label):
    """Draw a dashed orthogonal UML dependency without crossing package bodies."""
    assert len(points) >= 2
    assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:])), points
    if len(points) > 2:
        xs, ys = zip(*points[:-1])
        ax.plot(xs, ys, color=INK, linewidth=1.05, linestyle=(0, (5, 4)), zorder=1)
    ax.add_patch(
        FancyArrowPatch(
            points[-2],
            points[-1],
            arrowstyle="-|>",
            mutation_scale=9,
            linewidth=1.05,
            linestyle=(0, (5, 4)),
            facecolor=PAPER,
            edgecolor=INK,
            shrinkA=0,
            shrinkB=0,
            zorder=1,
        )
    )
    longest = max(zip(points, points[1:]), key=lambda segment: abs(segment[1][0] - segment[0][0]) + abs(segment[1][1] - segment[0][1]))
    x = (longest[0][0] + longest[1][0]) / 2
    y = (longest[0][1] + longest[1][1]) / 2
    ax.text(
        x,
        y - 8,
        f"«{label}»",
        ha="center",
        va="center",
        fontsize=6.2,
        color=INK,
        bbox={"facecolor": PAPER, "edgecolor": "none", "pad": 1.5},
        zorder=5,
    )


def build_figure():
    if sns is not None:
        sns.set_theme(style="white", font="DejaVu Sans")
    else:
        plt.rcParams.update({"font.family": "DejaVu Sans"})

    fig, ax = plt.subplots(figsize=(16, 9), facecolor=PAPER)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_xlim(0, 1600)
    ax.set_ylim(900, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor(PAPER)

    ax.text(38, 30, "AutoScheduler Package Diagram", fontsize=14, fontweight="bold", color=INK)
    ax.text(1562, 30, "UML PACKAGE VIEW", ha="right", fontsize=6.5, family="DejaVu Sans Mono", color=INK)

    package(ax, 35, 78, 1530, 770, "AutoScheduler Prototype", tab_width=260)

    package(ax, 72, 145, 286, 180, "Application Interface", tab_width=190)
    package(ax, 92, 190, 246, 108, "CLI & Demo", ["main.py", "autoscheduler/cli.py", "autoscheduler/demo.py", "dynamic_demo.py"], tab_width=135, font_size=6.5)

    package(ax, 72, 395, 286, 340, "Data & Evidence", tab_width=170)
    package(
        ax,
        92,
        440,
        246,
        112,
        "Linux Capture",
        ["capture_linux_trace.sh", "capture_linux_full.sh", "linux_trace.py", "real_traces.py"],
        tab_width=135,
        font_size=6.2,
    )
    package(
        ax,
        92,
        602,
        246,
        104,
        "Trace Preparation",
        ["real_clean.py", "real_features.py", "real_replay.py", "real_split.py"],
        tab_width=150,
        font_size=6.3,
    )

    package(ax, 430, 145, 500, 590, "Research & ML", tab_width=150)
    package(
        ax,
        452,
        195,
        214,
        208,
        "Offline Dataset",
        ["workloads.py", "features.py", "dataset.py", "real_dataset.py", "development_workloads.py"],
        tab_width=142,
        font_size=6.2,
    )
    package(
        ax,
        694,
        195,
        214,
        208,
        "Model Selection",
        ["model.py", "model_bakeoff.py", "real_bakeoff.py", "dynamic_training.py", "benefit.py"],
        tab_width=145,
        font_size=6.2,
    )
    package(
        ax,
        452,
        474,
        456,
        226,
        "Dynamic Routing & Evaluation",
        [
            "adaptive.py  ·  dynamic.py  ·  dynamic_v3_experiment.py",
            "evaluation.py  ·  experiments.py  ·  fairness.py",
            "latency.py  ·  mlfq_experiment.py  ·  priority_rr.py",
            "Model proposes policy; confidence, dwell and safety rules guard switches.",
        ],
        tab_width=245,
        font_size=6.1,
    )

    package(ax, 980, 145, 530, 375, "Scheduling Core", tab_width=160)
    package(
        ax,
        1002,
        195,
        232,
        276,
        "scheduler",
        ["fcfs.py", "sjf.py", "srtf.py", "round_robin.py", "priority.py", "priority_rr.py", "mlfq.py"],
        tab_width=112,
        font_size=6.4,
    )
    package(
        ax,
        1260,
        195,
        228,
        276,
        "simulator",
        ["process.py", "engine.py", "simulator.py", "gantt.py", "Shared clock, events, metrics and timeline"],
        tab_width=112,
        font_size=6.4,
    )

    package(ax, 980, 590, 530, 145, "Configuration & Results", tab_width=215)
    package(ax, 1002, 635, 224, 70, "Configuration", ["configs/real_desktop_ml.json"], tab_width=135, font_size=6.2)
    package(ax, 1260, 635, 228, 70, "Artifacts", ["data/  ·  artifacts/  ·  results/"], tab_width=105, font_size=6.3)

    dependency(ax, [(358, 235), (394, 235), (394, 265), (430, 265)], "uses")
    dependency(ax, [(358, 565), (394, 565), (394, 585), (430, 585)], "input")
    dependency(ax, [(930, 300), (955, 300), (955, 310), (980, 310)], "uses")
    dependency(ax, [(1118, 471), (1118, 492), (1374, 492), (1374, 471)], "calls")
    dependency(ax, [(1245, 520), (1245, 555), (1245, 555), (1245, 590)], "writes evidence")
    dependency(ax, [(559, 403), (559, 430), (801, 430), (801, 403)], "features + labels")
    dependency(ax, [(800, 403), (800, 452), (680, 452), (680, 474)], "frozen model")

    ax.plot([72, 1510], [785, 785], color=INK, linewidth=0.8)
    ax.text(72, 812, "DEPENDENCY KEY", fontsize=6.8, fontweight="bold", color=INK)
    ax.plot([185, 252], [808, 808], color=INK, linewidth=1.05, linestyle=(0, (5, 4)))
    ax.add_patch(FancyArrowPatch((252, 808), (270, 808), arrowstyle="-|>", mutation_scale=9, color=INK, linewidth=1.05))
    ax.text(282, 812, "package A depends on package B", fontsize=6.5, color=INK)
    ax.text(1510, 812, "Black-and-white presentation view · module names match repository files", ha="right", fontsize=6.3, color=INK)

    return fig


def main():
    output_dir = Path(__file__).resolve().parent
    fig = build_figure()
    svg_path = output_dir / "autoscheduler_package_diagram.svg"
    png_path = output_dir / "autoscheduler_package_diagram.png"
    fig.savefig(svg_path, format="svg", facecolor=PAPER, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(png_path, format="png", dpi=220, facecolor=PAPER, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    print(png_path)
    print(svg_path)


if __name__ == "__main__":
    main()
