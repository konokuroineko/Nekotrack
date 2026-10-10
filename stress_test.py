"""Long-running, deterministic-seed adversarial soak test for NekoTrack.

Run from any directory:
    python stress_test.py --minutes 10
    python stress_test.py --minutes 120 --seed 20261009
    python stress_test.py --seconds 30 --seed 7

The harness makes no live API requests and never opens the user's application
database. Repeated database tests use throwaway temporary directories.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import math
import os
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
TEST_FILES = (
    ROOT / "tests" / "test_adversarial_regressions.py",
    ROOT / "tests" / "test_chaos_resilience.py",
    ROOT / "tests" / "test_deep_stress.py",
)
MAX_SOAK_SECONDS = 5 * 60 * 60


def _resolve_duration(minutes, seconds=None):
    """Reject invalid or accidentally unbounded soak durations."""
    duration = seconds if seconds is not None else minutes * 60
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The soak duration must be a finite number greater than zero.")
    if duration > MAX_SOAK_SECONDS:
        raise ValueError("The soak duration cannot exceed 300 minutes (5 hours).")
    return duration


def load_adversarial_tests():
    """Load all seeded fuzz/chaos suites used in each soak iteration."""
    sys.path.insert(0, str(ROOT))
    modules = []
    for test_file in TEST_FILES:
        if not test_file.is_file():
            raise RuntimeError(f"Cannot load adversarial test module: {test_file}")
        module_name = f"nekotrack_stress_{test_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, test_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load adversarial test module: {test_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def run_full_regression_suite():
    """Run the entire repository test suite once before the soak loop."""
    env = os.environ.copy()
    env.pop("NEKOTRACK_FUZZ_SEED", None)
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=300,
        env=env,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "exit_code": completed.returncode,
        "output": output[-24000:],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run the full NekoTrack regression suite, then fuzz adversarial cases."
    )
    parser.add_argument("--minutes", type=float, default=10,
                        help="Soak duration in minutes (default: 10).")
    parser.add_argument("--seconds", type=float, default=None,
                        help="Optional soak duration in seconds; overrides --minutes.")
    parser.add_argument("--seed", type=int, default=20261009,
                        help="Starting seed. Each soak iteration gets a different seed.")
    parser.add_argument("--report", default="nekotrack_stress_report.json",
                        help="JSON report path (written under the repository if relative).")
    args = parser.parse_args()

    try:
        duration = _resolve_duration(args.minutes, args.seconds)
    except ValueError as error:
        parser.error(str(error))

    report = {
        "app": "NekoTrack",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_requested_seconds": duration,
        "starting_seed": args.seed,
        "network_requests_enabled": False,
        "real_application_database_touched": False,
        "fuzz_modules": [path.relative_to(ROOT).as_posix() for path in TEST_FILES],
        "max_soak_seconds": MAX_SOAK_SECONDS,
        "results": [],
        "stress_tests_run": 0,
        "stress_iterations": 0,
        "stress_passes": 0,
        "stress_failures": 0,
        "failure_samples": [],
        "interrupted": False,
    }

    print("NekoTrack adversarial stress test")
    print("=================================")
    print(f"Requested soak: {duration:g} seconds ({duration / 60:g} minutes)")
    print("Fuzz suites: " + ", ".join(path.name for path in TEST_FILES))
    print(f"Starting seed: {args.seed}")
    print("Live API access: disabled")
    print("Application database: never accessed")
    print("\nRunning the full regression suite first...")

    try:
        baseline = run_full_regression_suite()
        report["results"].append({"name": "Full regression suite", **baseline})
        print(baseline["output"])
        print(f"\nFull regression suite: {baseline['status']}")
    except Exception:
        baseline = {
            "status": "FAIL",
            "exit_code": -1,
            "output": traceback.format_exc()[-24000:],
        }
        report["results"].append({"name": "Full regression suite", **baseline})
        print(baseline["output"])

    try:
        modules = load_adversarial_tests()
    except Exception:
        report["results"].append({
            "name": "Load adversarial tests",
            "status": "FAIL",
            "output": traceback.format_exc(),
        })
        modules = None

    original_seed = os.environ.get("NEKOTRACK_FUZZ_SEED")
    rng = random.Random(args.seed)
    started = time.monotonic()
    deadline = started + duration
    next_progress = started + 10
    iteration = 0
    try:
        if modules:
            while time.monotonic() < deadline:
                seed = rng.randrange(1, 2**31 - 1)
                os.environ["NEKOTRACK_FUZZ_SEED"] = str(seed)
                output = io.StringIO()
                iteration_started = time.monotonic()
                try:
                    suite = unittest.TestSuite()
                    for stress_module in modules:
                        suite.addTests(
                            unittest.defaultTestLoader.loadTestsFromModule(stress_module)
                        )
                    result = unittest.TextTestRunner(
                        stream=output, verbosity=0, failfast=False
                    ).run(suite)
                    if result.testsRun == 0:
                        raise RuntimeError("No fuzz tests were loaded for this iteration.")
                    iteration += 1
                    report["stress_iterations"] = iteration
                    report["stress_tests_run"] += result.testsRun
                    iteration_elapsed = round(time.monotonic() - iteration_started, 3)
                    if result.wasSuccessful():
                        report["stress_passes"] += 1
                    else:
                        report["stress_failures"] += 1
                        detail = output.getvalue()
                        sample = {
                            "iteration": iteration,
                            "seed": seed,
                            "tests_run": result.testsRun,
                            "elapsed_seconds": iteration_elapsed,
                            "failures": len(result.failures),
                            "errors": len(result.errors),
                            "output": detail[-8000:],
                        }
                        if len(report["failure_samples"]) < 40:
                            report["failure_samples"].append(sample)
                except Exception:
                    iteration += 1
                    report["stress_iterations"] = iteration
                    report["stress_failures"] += 1
                    if len(report["failure_samples"]) < 40:
                        report["failure_samples"].append({
                            "iteration": iteration,
                            "seed": seed,
                            "elapsed_seconds": round(time.monotonic() - iteration_started, 3),
                            "failures": 0,
                            "errors": 1,
                            "output": traceback.format_exc()[-8000:],
                        })

                now = time.monotonic()
                if now >= next_progress:
                    elapsed = now - started
                    print(
                        f"[{elapsed:,.0f}s] iterations={report['stress_iterations']:,}, "
                        f"passed={report['stress_passes']:,}, "
                        f"failed={report['stress_failures']:,}, seed={seed}"
                    )
                    next_progress = now + 10
    except KeyboardInterrupt:
        report["interrupted"] = True
        print("\nInterrupted by user; writing the partial report.")
    finally:
        if original_seed is None:
            os.environ.pop("NEKOTRACK_FUZZ_SEED", None)
        else:
            os.environ["NEKOTRACK_FUZZ_SEED"] = original_seed

    report["duration_actual_seconds"] = round(time.monotonic() - started, 2)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = {
        "full_regression_suite": baseline.get("status", "FAIL"),
        "stress_iterations": report["stress_iterations"],
        "stress_passes": report["stress_passes"],
        "stress_failures": report["stress_failures"],
        "stress_tests_run": report["stress_tests_run"],
        "interrupted": report["interrupted"],
    }

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    try:
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nReport: {report_path}")
    except Exception:
        print("Could not write report:")
        print(traceback.format_exc())
        return 1

    print(
        "\nStress summary: "
        f"{report['stress_iterations']:,} iterations, "
        f"{report['stress_passes']:,} passed, "
        f"{report['stress_failures']:,} failed; "
        f"{report['duration_actual_seconds']:,.1f}s elapsed."
    )
    if any(item.get("status") == "FAIL" for item in report["results"]) or report["stress_failures"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
