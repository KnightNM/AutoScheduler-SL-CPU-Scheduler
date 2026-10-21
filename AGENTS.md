# AutoScheduler Agent Guide

## Project

Python 3.10+ single-CPU scheduling research simulator. Classical policies, adaptive experiments, fairness diagnostics, latency experiments, and MLFQ share the event-driven simulator in `simulator/`.

The next research track is real Linux desktop trace validation. Its frozen contract is `configs/real_desktop_ml.json`; validate it with:

```bash
.venv/bin/python main.py real-config
.venv/bin/python main.py real-trace-validate <canonical.jsonl>
tools/run_firefox_probe.sh --dry-run 8
```

## Research boundaries

- Keep existing synthetic experiments and historical results unchanged.
- Synthetic workloads are for tests, stress cases, and optional pretraining only; they cannot select the final ML model.
- Train and evaluate the real-data model only on observed history. Never expose future arrivals, declared total CPU/I/O work, true remaining burst, final outcomes, or oracle identity as features.
- `real-features` produces observed-only inputs, not policy-cost labels. Do not train or claim model performance from those rows alone.
- Deployable policies are FCFS, RR quantum 2, Priority, Priority-RR quantum 2 with aging 8 and switch cost 1, and MLFQ `(2, 4, 8)` with aging 20.
- True-burst SJF, SRTF, and RR20-SRTF are oracle-only references.
- Split complete application/scenario/capture groups; no group may cross train, validation, or locked test sets.
- Do not claim real scheduler performance from simulator timing. Linux capture/replay and end-to-end controller timing are separate evidence.
- Keep trace replay within `docs/OFFLINE_REPLAY_CONTRACT.md`; it supplies offline labels only, never a real-kernel performance claim.
- Do not begin `sched_ext` work until the locked real-trace gates pass.

## Commands

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python main.py demo --no-color
.venv/bin/python main.py real-config
.venv/bin/python main.py real-replay-build <canonical.jsonl> --output <manifest.json>
.venv/bin/python main.py real-trace-clean <canonical.jsonl> --capture-session <safe-id> --output <clean.jsonl>
.venv/bin/python main.py real-split <observed_features.csv> --output <split_manifest.json>
.venv/bin/python main.py real-dataset <cleaned.jsonl> --output <pilot_action_costs.csv>
.venv/bin/python main.py real-synthetic-capture --output <synthetic_raw.jsonl>
.venv/bin/python main.py model-bakeoff <pilot_action_costs.csv> --output <prototype_bakeoff_dir>
bash tools/capture_linux_full.sh --dry-run /tmp/full-collection 60 1
```

## Change rules

- Preserve unrelated dirty files and historical artifacts.
- Add tests before behavioral changes and run the focused test before the full suite.
- Use `apply_patch` for edits.
- Keep raw or processed trace data out of Git; commit only schemas, tiny fixtures, manifests, checksums, and summary results.
- Run `real-trace-clean` before sharing traces or extracting real-data feature/replay artifacts outside the private capture workspace. It rejects incomplete traces rather than hiding data loss.
- Before fitting any real-data model, create a `real-split` manifest. Keep full `(application, scenario, capture_session)` groups in one split; never split individual decision rows.
- `real-dataset` currently emits `pilot_offline_replay_development_only` labels. Never describe these as real kernel measurements or use them for final model selection.
- `real-synthetic-capture` generates trace-shaped development data only. Its bake-off status must remain `SYNTHETIC_DEVELOPMENT_ONLY` regardless of numerical gate values.
- Run the Firefox probe with its isolated temporary profile; do not reuse or inspect the user's normal browser profile.
- Use collector `--all-cpus` for multiprocess desktop workloads; CPU remains the requested workload affinity, not the trace coverage.
- Treat `capture_linux_pilot.sh` output as pipeline validation only; final data still follows the frozen repetition and duration contract.
- Stop at VM, credential, dataset-license, or kernel-access boundaries and ask the user for access.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
