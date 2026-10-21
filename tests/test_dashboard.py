"""Small adapter checks only; no training, dataset or benchmark pipeline."""
import json
import importlib.util
from pathlib import Path
import unittest


class DashboardTests(unittest.TestCase):
    def test_three_demos_preserve_service_and_final_wait_accounting(self):
        from dashboard.adapter import WORKLOADS, simulation
        for workload in WORKLOADS:
            for algorithm in ("FCFS", "SJF", "SRTF", "Round Robin", "Priority", "Priority RR", "MLFQ", "Tuned MLFQ"):
                with self.subTest(workload=workload, algorithm=algorithm):
                    result = simulation(workload, algorithm)
                    self.assertTrue(5 <= len(result["processes"]) <= 12)
                    self.assertEqual(len(result["frames"]), result["metrics"]["makespan"] + 1)
                    for process in result["processes"]:
                        service = sum(end-start for pid,start,end in result["timeline"] if pid == process["pid"])
                        self.assertEqual(service, process["burst_time"])
                        final = next(p for p in result["frames"][-1]["processes"] if p["pid"] == process["pid"])
                        self.assertEqual(final["state"], "Completed")
                        self.assertEqual(final["waiting_time"], process["waiting_time"])

    def test_io_and_pre_arrival_states_are_derived_from_actual_timeline(self):
        from dashboard.adapter import simulation
        result = simulation("mixed_io", "Round Robin")
        self.assertTrue(any(f["blocked"] for f in result["frames"]))
        for frame in result["frames"]:
            self.assertTrue(set(frame["ready"]).isdisjoint(frame["blocked"]))
            self.assertNotIn(frame["running"], frame["ready"])
            for process in frame["processes"]:
                if frame["tick"] < process["arrival_time"]:
                    self.assertEqual(process["state"], "Not arrived")
                    self.assertIsNone(process["response_time"])

    def test_saved_metrics_keep_their_provenance(self):
        from dashboard.adapter import catalog
        result = catalog()
        metadata = json.loads(Path("artifacts/demo_tree.json").read_text())
        self.assertEqual(result["offline"]["metadata"], metadata)
        self.assertEqual(result["research"], json.loads(Path("configs/research_status.json").read_text()))
        self.assertFalse(result["offline"]["inference_available"])

    @unittest.skipUnless(importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"), "optional dashboard HTTP test dependencies")
    def test_http_contract_rejects_unknown_ids_and_serves_small_comparison(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.get("/api/simulation", params={"workload":"../../etc/passwd"}).status_code, 404)
            self.assertEqual(client.get("/api/simulation", params={"algorithm":"unknown"}).status_code, 404)
            self.assertEqual(client.get("/configs/real_desktop_ml.json").status_code, 404)
            response = client.get("/api/comparison", params={"workload":"short_jobs"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["results"]), 9)
            self.assertTrue(all("score" in row for row in response.json()["results"]))


if __name__ == "__main__":
    unittest.main()
