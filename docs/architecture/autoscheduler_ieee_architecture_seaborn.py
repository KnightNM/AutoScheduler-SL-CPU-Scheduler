"""Render the AutoScheduler IEEE architecture as a 16:9 SVG or PNG."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

try:
    import seaborn as sns
except ModuleNotFoundError:  # Matplotlib is sufficient for the monochrome fallback.
    sns = None


INK = "#202020"
TEXT = "#121212"
MUTED = "#444440"
PAPER = "#f8f8f6"
PANEL = "#fdfdfb"
HEADER = "#ecece8"


def add_module(ax, x, y, width, height, title, lines, *, dashed=False):
    """Draw one compact module box with manually line-broken text."""
    assert not lines or 44 + (len(lines) - 1) * 15 <= height - 5
    box = Rectangle(
        (x, y),
        width,
        height,
        facecolor=PANEL,
        edgecolor=INK,
        linewidth=1.05,
        linestyle=(0, (5, 3)) if dashed else "solid",
        zorder=3,
    )
    ax.add_patch(box)
    ax.text(x + 12, y + 24, title, fontsize=7.6, fontweight="bold", color=TEXT, zorder=4)
    for index, (line, kind) in enumerate(lines):
        ax.text(
            x + 12,
            y + 44 + index * 15,
            line,
            fontsize=5.7 if kind == "body" else 5.35,
            fontweight="normal" if kind == "body" else "bold",
            family="DejaVu Sans" if kind == "body" else "DejaVu Sans Mono",
            color=MUTED if kind == "body" else "#333330",
            zorder=4,
        )


def add_stage(ax, x, width, title):
    ax.add_patch(Rectangle((x, 90), width, 620, facecolor="none", edgecolor=INK, linewidth=1.0))
    ax.add_patch(Rectangle((x, 90), width, 38, facecolor=HEADER, edgecolor=INK, linewidth=1.0))
    ax.text(x + 14, 115, title, fontsize=7.2, fontweight="bold", color=TEXT)


def add_connector(ax, points, *, dashed=False):
    """Draw an orthogonal connector whose final segment owns the arrowhead."""
    assert len(points) >= 2
    assert all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:])), points
    style = (0, (5, 4)) if dashed else "solid"
    if len(points) > 2:
        xs, ys = zip(*points[:-1])
        ax.plot(xs, ys, color=INK, linewidth=1.05, linestyle=style, zorder=2)
    ax.add_patch(
        FancyArrowPatch(
            points[-2],
            points[-1],
            arrowstyle="-|>",
            mutation_scale=8,
            linewidth=1.05,
            linestyle=style,
            color=INK,
            shrinkA=0,
            shrinkB=0,
            zorder=2,
        )
    )


def build_figure():
    if sns is not None:
        sns.set_theme(style="white", font="DejaVu Sans")
    else:
        plt.rcParams.update({"font.family": "DejaVu Sans", "axes.facecolor": PAPER})

    fig, ax = plt.subplots(figsize=(16, 9), facecolor=PAPER)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_xlim(0, 1600)
    ax.set_ylim(900, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor(PAPER)

    ax.text(34, 38, "AutoScheduler — Workload-Adaptive CPU Scheduling Architecture", fontsize=14, fontweight="bold")
    ax.text(
        34,
        62,
        "Offline evidence selects a model; guarded Dynamic V3 routing controls one shared scheduling engine.",
        fontsize=7.5,
        color=MUTED,
    )
    ax.text(1566, 38, "FIG. 1 · SINGLE CPU · DYNAMIC V3", ha="right", fontsize=6.2, family="DejaVu Sans Mono")

    add_stage(ax, 32, 280, "1 · INPUTS & ORCHESTRATION")
    add_stage(ax, 334, 292, "2 · DATA PREPARATION")
    add_stage(ax, 648, 300, "3 · LABELS & MODEL SELECTION")
    add_stage(ax, 970, 290, "4 · GUARDED DYNAMIC ROUTING")
    add_stage(ax, 1282, 286, "5 · EXECUTION & EVIDENCE")

    add_module(ax, 49, 150, 246, 66, "CLI / Experiment Orchestrator", [
        ("Starts train, bake-off, evaluate, and demo.", "body"),
        ("Freezes seeds, paths, and run configuration.", "body"),
    ])
    add_module(ax, 49, 252, 246, 86, "Seeded Workload Generator", [
        ("Synthetic arrivals, priorities, CPU/I/O bursts,", "body"),
        ("profiles, and changing workload phases.", "body"),
        ("tests · stress · development only", "mono"),
    ])
    add_module(ax, 49, 374, 246, 96, "Linux Trace Acquisition", [
        ("trace-cmd records wakeups, switches, blocks,", "body"),
        ("exits, priorities, and CPU activity.", "body"),
        ("capture → import → canonical JSONL", "mono"),
    ])
    add_module(ax, 49, 522, 246, 88, "Research Contract", [
        ("Fixes policies, weights, and feature rules.", "body"),
        ("Freezes seeds, latency gate, evidence scope.", "body"),
        ("configs/real_desktop_ml.json", "mono"),
    ], dashed=True)

    add_module(ax, 351, 252, 258, 86, "Process Model & Offline Replay", [
        ("Jobs have arrival, priority, and CPU/I/O bursts.", "body"),
        ("One CPU replays each job to completion.", "body"),
        ("Process · replay workload · completion", "mono"),
    ])
    add_module(ax, 351, 374, 258, 96, "Clean & Validate Real Traces", [
        ("Rejects incomplete captures and removes paths,", "body"),
        ("commands, usernames, and machine identifiers.", "body"),
        ("real-trace-clean · real-trace-validate", "mono"),
    ])
    add_module(ax, 351, 502, 258, 96, "Observed-Only Feature Extraction", [
        ("Queue, wait, service, I/O, priority, arrival,", "body"),
        ("and switch history before decision time.", "body"),
        ("observed-only · no hidden future data", "mono"),
    ])
    add_module(ax, 351, 622, 258, 66, "Group-Safe Train / Val / Test Split", [
        ("Keeps each trace/application in one split.", "body"),
        ("prevents related-row leakage", "mono"),
    ])

    add_module(ax, 665, 196, 266, 98, "Counterfactual Action-Cost Labels", [
        ("Replays every legal scheduler from one state.", "body"),
        ("Uses fixed score-normalization bounds.", "body"),
        ("target = estimated cost for each action", "mono"),
        ("offline estimate, not kernel proof", "mono"),
    ])
    add_module(ax, 665, 330, 266, 116, "Equal-Budget Model Bake-Off", [
        ("Every model uses the same rows and split:", "body"),
        ("Dummy · Ridge · Decision Tree", "mono"),
        ("Random Forest · Hist. Gradient Boosting", "mono"),
        ("Winner minimizes validation scheduling cost.", "body"),
    ])
    add_module(ax, 665, 478, 266, 82, "Dynamic V3 Tree Formulation Check", [
        ("Policy classification vs action-cost prediction.", "body"),
        ("accuracy · regret · realized cost", "mono"),
    ])
    add_module(ax, 665, 590, 266, 78, "Frozen Model Bundle", [
        ("Estimator, feature order, policy set, thresholds,", "body"),
        ("versioned metadata · joblib + JSON", "mono"),
    ])

    add_module(ax, 987, 156, 256, 76, "Unseen Changing Workload", [
        ("Jobs and workload phases arrive while", "body"),
        ("the simulation is already running.", "body"),
    ])
    add_module(ax, 987, 268, 256, 94, "Dynamic V3 Router", [
        ("Every 10 ticks, reads the observed state", "body"),
        ("and asks the frozen model for a policy.", "body"),
        ("features → model → proposed scheduler", "mono"),
    ])
    add_module(ax, 987, 398, 256, 112, "Safety & Stability Controller", [
        ("Switches only at a dispatch boundary.", "body"),
        ("confidence ≥ 0.80 · dwell ≥ 20 ticks", "mono"),
        ("gain ≥ margin · eligible policy", "mono"),
        ("Otherwise hold current policy or use MLFQ.", "body"),
    ])
    add_module(ax, 987, 546, 256, 124, "Scheduler Policy Bank", [
        ("Deployable: FCFS · RR · Priority · PRR · MLFQ", "mono"),
        ("Oracle-only references:", "body"),
        ("SJF · SRTF · RR20-SRTF", "mono"),
    ])

    add_module(ax, 1299, 194, 252, 122, "Shared Event-Driven Simulator", [
        ("One clock and dispatch engine for every policy.", "body"),
        ("arrivals · CPU · preempt · I/O return", "mono"),
        ("idle · switch cost · completion", "mono"),
        ("Policies choose; the engine executes.", "body"),
    ])
    add_module(ax, 1299, 350, 252, 82, "Process State Machine", [
        ("READY → RUNNING → BLOCKED → READY", "mono"),
        ("RUNNING → COMPLETED", "mono"),
    ])
    add_module(ax, 1299, 466, 252, 108, "Metrics & Evaluation", [
        ("Wait, response, turnaround, utilization,", "body"),
        ("throughput, fairness, regret, and latency.", "body"),
        ("paired tests · P50/P95/P99 · gates", "mono"),
        ("fixed weighted score normalization", "mono"),
    ])
    add_module(ax, 1299, 608, 252, 72, "Research Artifacts", [
        ("Models, CSV/JSON, decisions, Gantt chart,", "body"),
        ("plots, summaries, and presentation report.", "body"),
    ])

    connectors = [
        [(172, 216), (172, 252)],
        [(229, 216), (229, 230), (306, 230), (306, 357), (172, 357), (172, 374)],
        [(295, 295), (351, 295)],
        [(295, 422), (351, 422)],
        [(480, 338), (480, 356), (618, 356), (618, 486), (462, 486), (462, 502)],
        [(480, 470), (480, 486), (498, 486), (498, 502)],
        [(480, 598), (480, 622)],
        [(609, 295), (637, 295), (637, 245), (665, 245)],
        [(609, 655), (637, 655), (637, 388), (665, 388)],
        [(798, 294), (798, 330)],
        [(798, 446), (798, 478)],
        [(798, 560), (798, 590)],
        [(931, 629), (959, 629), (959, 315), (987, 315)],
        [(1115, 232), (1115, 268)],
        [(1115, 362), (1115, 398)],
        [(1115, 510), (1115, 546)],
        [(1243, 608), (1271, 608), (1271, 255), (1299, 255)],
        [(1425, 316), (1425, 350)],
        [(1425, 432), (1425, 466)],
        [(1425, 574), (1425, 608)],
    ]
    for points in connectors:
        add_connector(ax, points)
    add_connector(ax, [(295, 566), (321, 566), (321, 140), (957, 140), (957, 454), (987, 454)], dashed=True)
    ax.text(654, 152, "FROZEN EXPERIMENT + SAFETY CONTRACT", fontsize=5.5, fontweight="bold")

    ax.plot([32, 1568], [744, 744], color=INK, linewidth=0.9)
    footer = [
        (32, "1", "Collect work", "Generate jobs or capture Linux events."),
        (340, "2", "Build observations", "Use only facts known before a decision."),
        (648, "3", "Freeze model", "Compare candidates; lock one bundle."),
        (970, "4", "Route safely", "Model proposes; guard rules control."),
        (1282, "5", "Publish evidence", "Run one engine; report every result."),
    ]
    for x, number, title, copy in footer:
        ax.add_patch(Rectangle((x, 768), 24, 24, facecolor=INK, edgecolor=INK))
        ax.text(x + 12, 785, number, ha="center", color=PAPER, fontsize=7, fontweight="bold")
        ax.text(x + 34, 779, title, fontsize=6.7, fontweight="bold")
        ax.text(x + 34, 797, copy, fontsize=5.6, color=MUTED)

    ax.plot([32, 1568], [836, 836], color="#b4b4ae", linewidth=0.7)
    ax.text(32, 860, "SOLID = DATA / CONTROL", fontsize=5.6, family="DejaVu Sans Mono")
    ax.plot([258, 304], [856, 856], color=INK, linewidth=1.0, linestyle=(0, (5, 4)))
    ax.text(315, 860, "DASHED = CONFIGURATION / REFERENCE", fontsize=5.6, family="DejaVu Sans Mono")
    ax.text(1568, 860, "LOWER SCORE IS BETTER · ROUTING P99 TARGET < 10 ms", ha="right", fontsize=5.6, family="DejaVu Sans Mono")
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("autoscheduler_ieee_architecture_seaborn.svg"),
        help="Output .svg or .png path.",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure = build_figure()
    figure.savefig(args.output, dpi=200, facecolor=PAPER)
    plt.close(figure)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
