"""Regression tests for the CI adversarial stress harness."""
import subprocess
import unittest
from unittest.mock import patch

import stress_test


class StressHarnessTests(unittest.TestCase):
    def test_regression_suite_timeout_preserves_partial_test_output(self):
        timeout = subprocess.TimeoutExpired(
            cmd=["python", "-m", "unittest", "discover"],
            timeout=300,
            output=b"test_previous_case (tests.test_sample) ... ok\n",
            stderr=b"test_stalled_case (tests.test_sample) ...",
        )
        with patch("stress_test.subprocess.run", side_effect=timeout):
            result = stress_test.run_full_regression_suite()

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_seconds"], 300)
        self.assertIn("test_previous_case", result["output"])
        self.assertIn("test_stalled_case", result["output"])
        self.assertIn("timed out after 300 seconds", result["output"])


if __name__ == "__main__":
    unittest.main()
