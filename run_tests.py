"""Run the offline Python suite and save a machine-readable result summary.

Usage: python run_tests.py
Failures are intentionally left visible; application source is not repaired by
the test runner. See docs/TEST_REPORT.md for reproduced defects and coverage limits.
"""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "tests_run": result.testsRun,
        "passed": result.passed,
        "failures": [{"test": test.id(), "traceback": details} for test, details in result.failures],
        "errors": [{"test": test.id(), "traceback": details} for test, details in result.errors],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "scope": "Real application functions/HTTP handlers and temporary SQLite; mocked Firebase/AI/SMTP; no hardware or clinical validation.",
    }
    (output / "python-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sys.exit(0 if result.wasSuccessful() else 1)
