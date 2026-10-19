"""Import trace-cmd scheduler reports into the canonical observed trace format."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

from autoscheduler.real_traces import write_traces


LINE = re.compile(
    r"^\s*(?P<comm>.+)-(?P<caller>\d+)\s+\[(?P<cpu>\d+)\].*?"
    r"(?P<timestamp>\d+\.\d+):\s+(?P<name>[a-z0-9_]+):\s*(?P<body>.*)$"
)
EXEC = re.compile(r"filename=(?P<filename>\S+) pid=(?P<pid>\d+)")
FORK = re.compile(r"\bpid=(?P<parent>\d+).*\bchild_pid=(?P<child>\d+)")
EXIT = re.compile(r"\bpid=(?P<pid>\d+)\s+prio=(?P<priority>\d+)")
WAKEUP = re.compile(r".*:(?P<pid>\d+) \[(?P<priority>\d+)\] CPU:(?P<cpu>\d+)")
SWITCH = re.compile(
    r"(?P<prev_comm>.*):(?P<prev_pid>\d+) \[(?P<prev_priority>\d+)\] (?P<state>\S+)"
    r" ==> (?P<next_comm>.*):(?P<next_pid>\d+) \[(?P<next_priority>\d+)\]"
)


def _record(line: str) -> dict[str, Any] | None:
    match = LINE.match(line)
    if not match:
        return None
    values = match.groupdict()
    return {
        "comm": values["comm"].strip(),
        "caller": int(values["caller"]),
        "cpu": int(values["cpu"]),
        "timestamp_ns": int(Decimal(values["timestamp"]) * 1_000_000_000),
        "name": values["name"],
        "body": values["body"],
    }


def _event(record: dict[str, Any], pid: int, event_type: str, priority=None, **values) -> dict[str, Any]:
    return {
        "timestamp_ns": record["timestamp_ns"],
        "cpu": record["cpu"],
        "pid": pid,
        "type": event_type,
        "priority": priority,
        "previous_state": values.get("previous_state"),
        "ready_count": None,
        "wakeup_source": values.get("wakeup_source"),
    }


def import_trace_report(
    lines: Iterable[str], metadata: dict[str, Any], trace_id: str
) -> dict[str, Any]:
    records = [record for line in lines if (record := _record(line)) is not None]
    return _import_trace_records(lambda: iter(records), metadata, trace_id)


def _import_trace_records(
    records: Callable[[], Iterable[dict[str, Any]]],
    metadata: dict[str, Any],
    trace_id: str,
) -> dict[str, Any]:
    command = metadata.get("command") or []
    if not command:
        raise ValueError("capture metadata requires a workload command")
    application = Path(command[0]).name

    exec_records: dict[int, list[dict[str, Any]]] = {}
    forks: list[tuple[int, int, dict[str, Any]]] = []
    for record in records():
        if record["name"] == "sched_process_exec" and (match := EXEC.search(record["body"])):
            exec_records.setdefault(int(match["pid"]), []).append(
                {**record, "filename": match["filename"]}
            )
        elif record["name"] == "sched_process_fork" and (match := FORK.search(record["body"])):
            forks.append((int(match["parent"]), int(match["child"]), record))

    roots = {
        pid for pid, pid_records in exec_records.items()
        if any(Path(record["filename"]).name == application for record in pid_records)
    }
    if not roots:
        raise ValueError(f"{trace_id}: no exec event found for {application}")

    scoped = set(roots)
    changed = True
    while changed:
        changed = False
        for parent, child, _ in forks:
            if parent in scoped and child not in scoped:
                scoped.add(child)
                changed = True

    arrivals = {
        pid: next(
            record for record in exec_records[pid]
            if Path(record["filename"]).name == application
        )
        for pid in roots
    }
    parents: dict[int, int | None] = {pid: None for pid in roots}
    for parent, child, record in forks:
        if parent in scoped and child in scoped:
            arrivals.setdefault(child, record)
            parents[child] = parent

    completions: dict[int, dict[str, Any]] = {}
    priorities: dict[int, int] = {}
    events: list[dict[str, Any]] = []
    for pid, record in arrivals.items():
        events.append(_event(record, pid, "arrival"))

    for record in records():
        name, body = record["name"], record["body"]
        if name in {"sched_wakeup", "sched_wakeup_new"} and (match := WAKEUP.match(body)):
            pid, priority = int(match["pid"]), int(match["priority"])
            if pid in scoped:
                priorities.setdefault(pid, priority)
                events.append(_event(
                    record, pid, "wakeup", priority,
                    wakeup_source=record["caller"] if record["caller"] else None,
                ))
        elif name == "sched_switch" and (match := SWITCH.match(body)):
            previous_pid, next_pid = int(match["prev_pid"]), int(match["next_pid"])
            if previous_pid in scoped:
                priority = int(match["prev_priority"])
                priorities.setdefault(previous_pid, priority)
                events.append(_event(
                    record, previous_pid, "switch_out", priority,
                    previous_state=match["state"],
                ))
            if next_pid in scoped:
                priority = int(match["next_priority"])
                priorities.setdefault(next_pid, priority)
                events.append(_event(record, next_pid, "switch_in", priority))
        elif name == "block_rq_issue" and record["caller"] in scoped:
            events.append(_event(record, record["caller"], "block", priorities.get(record["caller"])))
        elif name == "sched_process_exit" and (match := EXIT.search(body)):
            pid, priority = int(match["pid"]), int(match["priority"])
            if pid in scoped:
                priorities.setdefault(pid, priority)
                completions[pid] = record
                events.append(_event(record, pid, "exit", priority))

    events.sort(key=lambda event: event["timestamp_ns"])
    processes = []
    for pid in sorted(scoped):
        completion = completions.get(pid)
        processes.append({
            "pid": pid,
            "arrival_ns": arrivals[pid]["timestamp_ns"],
            "completion_ns": completion["timestamp_ns"] if completion else None,
            "priority": priorities.get(pid),
            "parent_pid": parents.get(pid),
            "cgroup": None,
            "application_family": application,
            "truncated": completion is None,
        })
    truncated = any(process["truncated"] for process in processes)
    return {
        "schema_version": 1,
        "metadata": {
            "trace_id": trace_id,
            "source": "linux",
            "source_url": None,
            "license": None,
            "application": application,
            "workload_family": metadata.get("workload_family"),
            "scenario": metadata.get("scenario"),
            "configuration_id": metadata.get("configuration_id"),
            "capture_session": trace_id,
            "machine_id": metadata.get("hostname"),
            "kernel_version": metadata.get("kernel"),
            "scheduler": metadata.get("scheduler"),
            "affinity_cpu": metadata.get("affinity_cpu", metadata.get("cpu")),
            "trace_cpus": metadata.get("trace_cpus"),
            "anonymized": False,
            "truncated": truncated,
        },
        "events": events,
        "processes": processes,
        "outcomes": [],
    }


def import_trace_files(
    report_path: str | Path,
    metadata_path: str | Path,
    output_path: str | Path,
    trace_id: str,
) -> dict[str, Any]:
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    report_path = Path(report_path)

    def records() -> Iterable[dict[str, Any]]:
        with report_path.open(encoding="utf-8") as report:
            for line in report:
                if (record := _record(line)) is not None:
                    yield record

    trace = _import_trace_records(records, metadata, trace_id)
    write_traces([trace], output_path)
    return trace
