# AutoScheduler review dashboard

React + Vite UI and a small, read-only FastAPI adapter. No model fitting,
dataset generation, benchmark runs, trace capture, or external services.

## Tomorrow's demo

From the repository root, dependencies and frontend are already installed/built:

```bash
bash dashboard/start.sh
```

Open **http://127.0.0.1:8000**. Stop with Ctrl+C. If port 8000 is occupied,
use `PORT=8001 bash dashboard/start.sh` and open port 8001 instead.
Startup needs no internet and serves the built UI and API from one local server.
Keep this repository's existing artifacts, configs and saved results alongside it.

First-time setup on another checkout (Node 20.19+ or 22.12+, Python 3.10+):

```bash
bash dashboard/setup.sh
bash dashboard/start.sh
```

Setup downloads the small frontend/runtime dependencies and builds the UI;
the demo itself makes no internet requests. It does not install Azure tooling,
load Azure datasets, or require a Linux collector/VM. `package-lock.json` and
the dashboard runtime requirements pin the installed dependencies. Existing
project dependencies are unchanged.

## Suggested review path

The Research page also reads `results/azure_external_pilot/summary.json` when
available. This separate Azure-derived pilot is not synthetic accuracy or real
kernel validation. The dashboard reads saved results only; startup never reruns
the pilot. See its REPORT.md for exact selections and the excluded peak snapshot.

1. **Overview:** explain the architecture and three separate scheduling tracks.
2. **Scheduling lab:** choose Mixed CPU / I/O and Round Robin. Start, Pause,
   Step, Resume, and Reset. Change algorithm to show real schedule differences.
3. **ML intelligence:** explain the verified offline classifier metadata, v5/v6
   cohort-specific results, and live comparison on the same tiny workload.
4. **Research & review:** show the offline replay pilot's insufficient-data
   status and expand the twelve faculty questions.

## What works

- Three hand-defined deterministic workloads, six or eight processes each.
- All six traditional simulated policies, default MLFQ and the manifest's
  recommended tuned MLFQ. Oracle SJF/SRTF are labeled clearly.
- Start/Pause/Resume/Step/Reset and speed adjustment, animated native SVG timeline,
  CPU state, ready/blocked membership, per-process timings and final metrics.
- Actual same-workload comparisons with the existing scoring function and fixed
  six-policy reference bounds; all calculations run through the Python simulator.
- Saved classifier accuracy, sample counts, feature importance and label counts;
  dynamic research cohorts, measured units, actual safety gates and provenance.
- Read-only saved research, pilot model comparisons and faculty explanations.
- Keyboard-accessible native controls, responsive navigation, friendly errors,
  no external fonts, chart packages or UI libraries.

## Boundaries and limitations

- Replay runs Python once per selected workload/policy and returns bounded frames;
  animation does not call Python every tick. Tiny results are cached in memory.
- Ready membership is reconstructed in Python from the real timeline and declared
  CPU/I/O bursts. **Internal policy queue order is not exposed.** This is replay,
  not a second browser scheduling implementation. Waiting excludes blocked time.
- The offline classifier's matching fitted six-policy binary is absent. The UI
  says live prediction is unavailable and shows verified metadata instead.
  Saved class counts are labels, not fabricated predictions.
- Dynamic ML is presented as saved research, not live policy switching. No model
  is promoted or represented as a real operating-system scheduler.
- Research cohorts stay separate. The v6 main experiment used a different tuned
  static comparator; its sensitivity check is explicitly marked explanatory.
- Percent utilization converts the simulator's fraction to a percentage.
  Timing otherwise uses simulator ticks; controller P99 uses milliseconds.
- No arbitrary uploads, process editing, authentication, database or deployment
  features. The server binds to loopback for this local academic demonstration.

## Lightweight checks

```bash
npm --prefix dashboard/web run build
# HTTP tests additionally use httpx; already installed in this workspace.
.venv/bin/python -m unittest tests.test_dashboard -v
```

Optional browser proof: `dashboard/browser-smoke.cjs` uses an existing Playwright
installation (`PLAYWRIGHT_MODULE`) and Chromium (`CHROME`). These are development
tools, not frontend/runtime dependencies. It checks all 24 demo/policy pairs,
playback, cohort selection, FAQ, console errors, external requests and page
overflow at 1440/1024/768/320px. Screenshots go to `/tmp`, not historical reports.

For frontend development only: run the backend and
`npm --prefix dashboard/web run dev`; Vite proxies `/api` to local port 8000.
Rebuild before using the one-command production-style demo again.
