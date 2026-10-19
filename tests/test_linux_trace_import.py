import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPORT = """cpus=4
          <idle>-0 [000] d..2. 10.000000: sched_switch: swapper/0:0 [120] R ==> taskset:100 [120]
       stress-ng-100 [000] ..... 10.000100: sched_process_exec: filename=/usr/bin/stress-ng pid=100 old_pid=100
       stress-ng-100 [000] ..... 10.000200: sched_process_fork: comm=stress-ng pid=100 child_comm=stress-ng child_pid=101
          <idle>-0 [000] dNh4. 10.000300: sched_wakeup: stress-ng-cpu:101 [120] CPU:000
   stress-ng-cpu-101 [000] d..2. 10.000400: sched_switch: stress-ng-cpu:101 [120] D ==> swapper/0:0 [120]
   stress-ng-cpu-101 [000] ...1. 10.000500: block_rq_issue: 259,0 R 0 () 1 + 1 [stress-ng-cpu]
     unrelated-999 [000] d..2. 10.000600: sched_switch: unrelated:999 [120] R ==> swapper/0:0 [120]
   stress-ng-cpu-101 [000] ..... 10.000700: sched_process_exit: comm=stress-ng-cpu pid=101 prio=120 group_dead=true
       stress-ng-100 [000] ..... 10.000800: sched_process_exit: comm=stress-ng pid=100 prio=120 group_dead=true
"""

WRAPPER_REPORT = """cpus=4
            bash-200 [000] ..... 20.000000: sched_process_exec: filename=/usr/bin/taskset pid=200 old_pid=200
            bash-200 [000] ..... 20.000100: sched_process_exec: filename=/opt/autoscheduler/run_probe.sh pid=200 old_pid=200
            bash-200 [000] ..... 20.000200: sched_process_exec: filename=/usr/bin/bash pid=200 old_pid=200
            bash-200 [000] ..... 20.000300: sched_process_fork: comm=bash pid=200 child_comm=firefox child_pid=201
         firefox-201 [000] ..... 20.000400: sched_process_exec: filename=/usr/bin/firefox pid=201 old_pid=201
         firefox-201 [000] ..... 20.000500: sched_process_exit: comm=firefox pid=201 prio=120 group_dead=true
            bash-200 [000] ..... 20.000600: sched_process_exit: comm=bash pid=200 prio=120 group_dead=true
"""

METADATA = {
    "schema_version": 1,
    "source": "linux",
    "hostname": "fixture-vm",
    "kernel": "6.19-fixture",
    "architecture": "aarch64",
    "cpu": 0,
    "command": ["stress-ng", "--cpu", "1"],
    "capture_user": "tester",
}


class LinuxTraceImportTests(unittest.TestCase):
    def test_wrapper_exec_match_survives_later_interpreter_exec(self):
        from autoscheduler.linux_trace import import_trace_report

        metadata = {**METADATA, "command": ["/opt/autoscheduler/run_probe.sh"]}
        trace = import_trace_report(WRAPPER_REPORT.splitlines(), metadata, "wrapper")

        self.assertEqual([process["pid"] for process in trace["processes"]], [200, 201])
        self.assertEqual(trace["processes"][0]["arrival_ns"], 20_000_100_000)

    def test_import_scopes_workload_tree_and_maps_observed_events(self):
        from autoscheduler.linux_trace import import_trace_report
        from autoscheduler.real_traces import validate_trace

        trace = import_trace_report(
            REPORT.splitlines(),
            {**METADATA, "scenario": "cpu-ackermann", "configuration_id": "cpu-ackermann"},
            "capture-1",
        )
        validate_trace(trace)

        self.assertEqual([process["pid"] for process in trace["processes"]], [100, 101])
        self.assertNotIn(999, [event["pid"] for event in trace["events"]])
        self.assertEqual(trace["metadata"]["machine_id"], "fixture-vm")
        self.assertEqual(trace["metadata"]["application"], "stress-ng")
        self.assertEqual(trace["metadata"]["affinity_cpu"], 0)
        self.assertEqual(trace["metadata"]["scenario"], "cpu-ackermann")
        self.assertEqual(trace["metadata"]["configuration_id"], "cpu-ackermann")
        self.assertIn("wakeup", [event["type"] for event in trace["events"]])
        self.assertIn("block", [event["type"] for event in trace["events"]])
        self.assertEqual(trace["processes"][1]["parent_pid"], 100)
        self.assertFalse(trace["metadata"]["truncated"])

    def test_missing_exit_is_explicitly_truncated(self):
        from autoscheduler.linux_trace import import_trace_report

        trace = import_trace_report(REPORT.splitlines()[:-2], METADATA, "capture-2")

        self.assertTrue(trace["metadata"]["truncated"])
        self.assertTrue(all(process["truncated"] for process in trace["processes"]))

    def test_file_import_writes_canonical_jsonl(self):
        from autoscheduler.linux_trace import import_trace_files
        from autoscheduler.real_traces import read_traces

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "trace.txt"
            metadata = root / "metadata.json"
            output = root / "canonical.jsonl"
            report.write_text(REPORT, encoding="utf-8")
            metadata.write_text(json.dumps(METADATA), encoding="utf-8")

            import_trace_files(report, metadata, output, "capture-3")

            self.assertEqual(read_traces(output)[0]["metadata"]["trace_id"], "capture-3")

    def test_file_import_streams_report_instead_of_reading_it_whole(self):
        from autoscheduler.linux_trace import import_trace_files

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "trace.txt"
            metadata = root / "metadata.json"
            output = root / "canonical.jsonl"
            report.write_text(REPORT, encoding="utf-8")
            metadata.write_text(json.dumps(METADATA), encoding="utf-8")
            original_read_text = Path.read_text

            def guarded_read_text(path, *args, **kwargs):
                if path == report:
                    raise AssertionError("report must not be loaded into memory at once")
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", guarded_read_text):
                trace = import_trace_files(report, metadata, output, "capture-streamed")

            self.assertEqual(trace["metadata"]["trace_id"], "capture-streamed")

    def test_cli_imports_and_validates_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "trace.txt"
            metadata = root / "metadata.json"
            output = root / "canonical.jsonl"
            report.write_text(REPORT, encoding="utf-8")
            metadata.write_text(json.dumps(METADATA), encoding="utf-8")

            imported = subprocess.run(
                [sys.executable, "main.py", "real-trace-import", "--report", report,
                 "--metadata", metadata, "--output", output, "--trace-id", "capture-cli"],
                check=True, capture_output=True, text=True,
            )
            validated = subprocess.run(
                [sys.executable, "main.py", "real-trace-validate", output],
                check=True, capture_output=True, text=True,
            )

            self.assertIn("Processes: 2", imported.stdout)
            self.assertIn("Valid traces: 1", validated.stdout)


if __name__ == "__main__":
    unittest.main()
