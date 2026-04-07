#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any


def load_benchmark_means(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    means = {}
    for benchmark in data.get("benchmarks", []):
        metadata = benchmark.get("metadata", {})
        name = metadata.get("name") or benchmark.get("name")
        if not name:
            continue

        values = []
        for run in benchmark.get("runs", []):
            values.extend(float(value) for value in run.get("values", []))

        if values:
            means[str(name)] = statistics.fmean(values)

    return means


def _geomean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot compute geomean of an empty value list")
    if any(value <= 0.0 for value in values):
        raise ValueError("all speedup values must be positive")
    return math.exp(statistics.fmean(math.log(value) for value in values))


def calculate_speedup_summary(
    baseline: dict[str, float],
    changed: dict[str, float],
    threshold: float,
) -> dict[str, Any]:
    common_names = sorted(set(baseline) & set(changed))
    if not common_names:
        raise ValueError("no common benchmarks found")

    rows = []
    speedups = []
    for name in common_names:
        baseline_mean = baseline[name]
        changed_mean = changed[name]
        if baseline_mean <= 0.0 or changed_mean <= 0.0:
            raise ValueError(f"benchmark {name!r} has non-positive mean runtime")

        speedup = baseline_mean / changed_mean
        speedups.append(speedup)
        rows.append(
            {
                "name": name,
                "baseline_mean": baseline_mean,
                "changed_mean": changed_mean,
                "speedup": speedup,
                "delta_pct": ((changed_mean / baseline_mean) - 1.0) * 100.0,
            }
        )

    geomean_speedup = _geomean(speedups)
    return {
        "threshold": threshold,
        "geomean_speedup": geomean_speedup,
        "passed": geomean_speedup >= threshold,
        "common_benchmark_count": len(common_names),
        "baseline_only": sorted(set(baseline) - set(changed)),
        "changed_only": sorted(set(changed) - set(baseline)),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--changed", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=1.02)
    args = parser.parse_args(argv)

    summary = calculate_speedup_summary(
        load_benchmark_means(args.baseline),
        load_benchmark_means(args.changed),
        args.threshold,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(
        "geomean_speedup="
        f"{summary['geomean_speedup']:.4f}x "
        f"threshold={summary['threshold']:.4f}x "
        f"passed={summary['passed']}"
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
