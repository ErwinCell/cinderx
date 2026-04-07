import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "arm"
    / "pyperf_speedup_summary.py"
)
SPEC = importlib.util.spec_from_file_location("pyperf_speedup_summary", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
pyperf_speedup_summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pyperf_speedup_summary)


def _write_pyperf_json(path: Path, values: dict[str, list[float]]) -> None:
    payload = {
        "benchmarks": [
            {
                "metadata": {"name": name},
                "runs": [{"values": benchmark_values}],
            }
            for name, benchmark_values in values.items()
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class PyperfSpeedupSummaryTests(unittest.TestCase):
    def test_calculates_common_benchmark_geomean_speedup(self) -> None:
        baseline = {"a": 2.0, "b": 8.0, "baseline-only": 1.0}
        changed = {"a": 1.0, "b": 4.0, "changed-only": 1.0}

        summary = pyperf_speedup_summary.calculate_speedup_summary(
            baseline,
            changed,
            1.02,
        )

        self.assertEqual(summary["common_benchmark_count"], 2)
        self.assertAlmostEqual(summary["geomean_speedup"], 2.0)
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["baseline_only"], ["baseline-only"])
        self.assertEqual(summary["changed_only"], ["changed-only"])

    def test_main_returns_failure_when_speedup_is_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            changed = tmp_path / "changed.json"
            output = tmp_path / "summary.json"
            _write_pyperf_json(baseline, {"a": [1.0, 1.0], "b": [2.0]})
            _write_pyperf_json(changed, {"a": [1.0, 1.0], "b": [2.0]})

            rc = pyperf_speedup_summary.main(
                [
                    "--baseline",
                    str(baseline),
                    "--changed",
                    str(changed),
                    "--output",
                    str(output),
                    "--threshold",
                    "1.02",
                ]
            )

            self.assertEqual(rc, 1)
            self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["passed"])


if __name__ == "__main__":
    unittest.main()
