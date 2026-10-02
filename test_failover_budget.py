import json
import subprocess
import sys
import unittest

from failover_budget import compute_budget, verdict, human, main


class TestComputeBudget(unittest.TestCase):
    def test_probe_detection_is_interval_times_fall(self):
        r = compute_budget(5, 3, 600, 0)
        self.assertEqual(r["probe_detection_seconds"], 15.0)

    def test_total_sums_all_terms(self):
        r = compute_budget(5, 3, 600, 265)
        self.assertEqual(r["user_visible_recovery_seconds"], 880.0)

    def test_zero_terms(self):
        r = compute_budget(1, 1, 0, 0)
        self.assertEqual(r["user_visible_recovery_seconds"], 1.0)

    def test_fractional_interval(self):
        r = compute_budget(2.5, 4, 30, 10)
        self.assertEqual(r["probe_detection_seconds"], 10.0)
        self.assertEqual(r["user_visible_recovery_seconds"], 50.0)


class TestVerdict(unittest.TestCase):
    def test_within_target_is_inclusive(self):
        self.assertEqual(verdict(60, 60), "WITHIN_TARGET")

    def test_over_target(self):
        self.assertEqual(verdict(61, 60), "OVER_TARGET")

    def test_typical_sloppy_config_is_over(self):
        # 5s x 3 probes + 600s TTL + 60s cache
        self.assertEqual(verdict(15 + 600 + 60, 60), "OVER_TARGET")


class TestHuman(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(human(45), "45s")

    def test_minutes(self):
        self.assertEqual(human(880), "14m 40s")

    def test_hours(self):
        self.assertEqual(human(7500), "2h 5m")


class TestCLI(unittest.TestCase):
    def test_exit_code_over_target(self):
        self.assertEqual(main(["--ttl", "600"]), 1)

    def test_exit_code_within_target(self):
        self.assertEqual(
            main(["--ttl", "10", "--cache-propagation", "5", "--target", "60"]), 0
        )

    def test_json_output_structure(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--json", "--ttl", "300"])
        data = json.loads(buf.getvalue())
        self.assertIn("verdict", data)
        self.assertIn("user_visible_recovery_seconds", data)
        self.assertEqual(data["verdict"], "OVER_TARGET")


class TestScriptRun(unittest.TestCase):
    def test_subprocess_runs(self):
        proc = subprocess.run(
            [sys.executable, "failover_budget.py", "--ttl", "300", "--json"],
            capture_output=True,
            text=True,
        )
        self.assertIn("user_visible_recovery_seconds", proc.stdout)
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
