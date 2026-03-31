#!/usr/bin/env python3
"""Run pyperformance benchmarks directly after import, outside pyperformance run."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import runpy
import statistics
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_KINDS = {"bench_time_func", "bench_func", "bench_async_func"}


@dataclass
class CapturedEntry:
    kind: str
    name: str
    target: Any | None
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    metadata: dict[str, Any]
    command: list[str] | None = None


def aggregate_deopts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any, Any, Any], int] = {}
    for event in events:
        key = (
            event["normal"].get("func_qualname"),
            event["int"].get("lineno"),
            event["normal"].get("description"),
            event["normal"].get("reason"),
        )
        grouped[key] = grouped.get(key, 0) + int(event["int"].get("count", 0))

    rows = []
    for (qualname, lineno, description, reason), count in grouped.items():
        rows.append(
            {
                "qualname": qualname,
                "lineno": lineno,
                "description": description,
                "reason": reason,
                "count": count,
            }
        )
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return repr(value)


def load_manifest_benchmarks() -> list[Any]:
    import pyperformance._manifest as manifest

    return list(manifest.load_manifest(None).benchmarks)


def resolve_manifest_benchmark(name: str) -> Any:
    for bench in load_manifest_benchmarks():
        if bench.name == name:
            return bench
    raise KeyError(f"unknown pyperformance benchmark: {name}")


def capture_entries(runscript: str, argv: list[str]) -> list[CapturedEntry]:
    import pyperf

    captured: list[CapturedEntry] = []
    runner_cls = pyperf.Runner
    saved_methods = {}
    saved_argv = sys.argv[:]
    saved_orig_argv = list(getattr(sys, "orig_argv", []))

    def capture(kind: str):
        def _capture(
            runner: Any,
            name: str,
            target: Any,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            captured.append(
                CapturedEntry(
                    kind=kind,
                    name=name,
                    target=target,
                    args=args,
                    kwargs=kwargs,
                    metadata=dict(getattr(runner, "metadata", {})),
                )
            )

        return _capture

    def capture_command(runner: Any, name: str, command: list[str]) -> None:
        captured.append(
            CapturedEntry(
                kind="bench_command",
                name=name,
                target=None,
                args=(),
                kwargs={},
                metadata=dict(getattr(runner, "metadata", {})),
                command=list(command),
            )
        )

    patch_methods = {
        "bench_time_func": capture("bench_time_func"),
        "bench_func": capture("bench_func"),
        "bench_async_func": capture("bench_async_func"),
        "bench_command": capture_command,
    }

    try:
        for name, replacement in patch_methods.items():
            if hasattr(runner_cls, name):
                saved_methods[name] = getattr(runner_cls, name)
                setattr(runner_cls, name, replacement)

        runner_cls._created.clear()
        sys.argv = [runscript, *argv]
        sys.orig_argv = [runscript, *argv]
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                runpy.run_path(runscript, run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
    finally:
        for name, original in saved_methods.items():
            setattr(runner_cls, name, original)
        runner_cls._created.clear()
        sys.argv = saved_argv
        if saved_orig_argv:
            sys.orig_argv = saved_orig_argv
        elif hasattr(sys, "orig_argv"):
            delattr(sys, "orig_argv")

    return captured


def configure_jit(compile_after_n_calls: int, specialized_opcodes: bool) -> Any:
    import cinderx.jit as jit

    jit.enable()
    jit.compile_after_n_calls(compile_after_n_calls)
    if specialized_opcodes:
        jit.enable_specialized_opcodes()
    else:
        jit.disable_specialized_opcodes()
    return jit


def _run_sync_target(
    entry: CapturedEntry,
    bench_time_loops: int,
    func_loops: int,
) -> Any:
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink):
            with contextlib.redirect_stderr(sink):
                if entry.kind == "bench_time_func":
                    return entry.target(bench_time_loops, *entry.args, **entry.kwargs)

                result = None
                for _ in range(func_loops):
                    result = entry.target(*entry.args, **entry.kwargs)
                return result


def _run_async_target(entry: CapturedEntry, func_loops: int) -> Any:
    with open(os.devnull, "w", encoding="utf-8") as sink:
        with contextlib.redirect_stdout(sink):
            with contextlib.redirect_stderr(sink):
                result = None
                for _ in range(func_loops):
                    result = asyncio.run(entry.target(*entry.args, **entry.kwargs))
                return result


def run_entry(
    entry: CapturedEntry,
    *,
    compile_after_n_calls: int,
    specialized_opcodes: bool,
    prewarm_runs: int,
    samples: int,
    bench_time_loops: int,
    func_loops: int,
) -> dict[str, Any]:
    if entry.kind not in SUPPORTED_KINDS:
        return {
            "name": entry.name,
            "kind": entry.kind,
            "status": "skipped",
            "skip_reason": (
                "bench_command relies on subprocess/startup timing and cannot "
                "safely use the after-import JIT runner"
            ),
            "metadata": _json_safe(entry.metadata),
            "command": _json_safe(entry.command),
        }

    jit = configure_jit(compile_after_n_calls, specialized_opcodes)

    for _ in range(prewarm_runs):
        if entry.kind == "bench_async_func":
            _run_async_target(entry, func_loops)
        else:
            _run_sync_target(entry, bench_time_loops, func_loops)

    samples_out = []
    all_deopts = []
    for _ in range(samples):
        jit.get_and_clear_runtime_stats()
        t0 = time.perf_counter()
        if entry.kind == "bench_async_func":
            result = _run_async_target(entry, func_loops)
        else:
            result = _run_sync_target(entry, bench_time_loops, func_loops)
        wall = time.perf_counter() - t0
        stats = jit.get_and_clear_runtime_stats()
        samples_out.append(
            {
                "result": _json_safe(result),
                "wall_sec": wall,
            }
        )
        all_deopts.extend(stats.get("deopt", []))

    return {
        "name": entry.name,
        "kind": entry.kind,
        "status": "ok",
        "metadata": _json_safe(entry.metadata),
        "args": _json_safe(entry.args),
        "kwargs": _json_safe(entry.kwargs),
        "samples": samples_out,
        "median_wall_sec": statistics.median(
            sample["wall_sec"] for sample in samples_out
        ),
        "min_wall_sec": min(sample["wall_sec"] for sample in samples_out),
        "total_deopt_count": sum(
            int(event["int"].get("count", 0)) for event in all_deopts
        ),
        "top_deopts": aggregate_deopts(all_deopts)[:12],
    }


def run_manifest_benchmark(
    benchmark_name: str,
    *,
    compile_after_n_calls: int,
    specialized_opcodes: bool,
    prewarm_runs: int,
    samples: int,
    bench_time_loops: int,
    func_loops: int,
    probe_only: bool,
) -> dict[str, Any]:
    bench = resolve_manifest_benchmark(benchmark_name)
    entries = capture_entries(bench.runscript, list(bench.extra_opts))

    result = {
        "manifest_name": bench.name,
        "runscript": bench.runscript,
        "extra_opts": list(bench.extra_opts),
        "tags": list(getattr(bench, "tags", [])),
        "entries": [],
    }

    for entry in entries:
        if probe_only:
            if entry.kind in SUPPORTED_KINDS:
                status = "supported"
                skip_reason = None
            else:
                status = "skipped"
                skip_reason = (
                    "bench_command relies on subprocess/startup timing and "
                    "stays on the unsupported path"
                )
            result["entries"].append(
                {
                    "name": entry.name,
                    "kind": entry.kind,
                    "status": status,
                    "skip_reason": skip_reason,
                    "metadata": _json_safe(entry.metadata),
                    "command": _json_safe(entry.command),
                }
            )
            continue

        result["entries"].append(
            run_entry(
                entry,
                compile_after_n_calls=compile_after_n_calls,
                specialized_opcodes=specialized_opcodes,
                prewarm_runs=prewarm_runs,
                samples=samples,
                bench_time_loops=bench_time_loops,
                func_loops=func_loops,
            )
        )

    statuses = [entry["status"] for entry in result["entries"]]
    if statuses and all(status in {"ok", "supported"} for status in statuses):
        result["status"] = "ok"
    elif statuses and all(status == "skipped" for status in statuses):
        result["status"] = "skipped"
    elif any(status in {"ok", "supported"} for status in statuses):
        result["status"] = "partial"
    else:
        result["status"] = "empty"
    if result["status"] == "skipped":
        reasons = [
            entry.get("skip_reason")
            for entry in result["entries"]
            if entry.get("skip_reason")
        ]
        if reasons:
            result["skip_reason"] = reasons[0] if len(set(reasons)) == 1 else reasons
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--single-benchmark",
        default="",
        help="Run one manifest benchmark name and print a single JSON payload",
    )
    parser.add_argument(
        "--benchmarks",
        default="",
        help="Comma-separated manifest benchmark names. Empty means all.",
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--prewarm-runs", type=int, default=2)
    parser.add_argument("--bench-time-loops", type=int, default=1)
    parser.add_argument("--func-loops", type=int, default=1)
    parser.add_argument("--compile-after-n-calls", type=int, default=2)
    parser.add_argument("--specialized-opcodes", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "manifest_benchmarks": len(rows),
        "ok": 0,
        "partial": 0,
        "skipped": 0,
        "empty": 0,
        "errors": 0,
        "entry_ok": 0,
        "entry_skipped": 0,
        "entry_errors": 0,
    }
    for row in rows:
        status = row.get("status")
        if status == "ok":
            summary["ok"] += 1
        elif status == "partial":
            summary["partial"] += 1
        elif status == "skipped":
            summary["skipped"] += 1
        elif status == "empty":
            summary["empty"] += 1
        elif status == "error":
            summary["errors"] += 1
        for entry in row.get("entries", []):
            entry_status = entry.get("status")
            if entry_status in {"ok", "supported"}:
                summary["entry_ok"] += 1
            elif entry_status == "skipped":
                summary["entry_skipped"] += 1
            elif entry_status == "error":
                summary["entry_errors"] += 1
    return summary


def _write_output(path: str, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")


def main() -> int:
    args = build_parser().parse_args()

    if args.single_benchmark:
        try:
            payload = run_manifest_benchmark(
                args.single_benchmark,
                compile_after_n_calls=args.compile_after_n_calls,
                specialized_opcodes=args.specialized_opcodes,
                prewarm_runs=args.prewarm_runs,
                samples=args.samples,
                bench_time_loops=args.bench_time_loops,
                func_loops=args.func_loops,
                probe_only=args.probe_only,
            )
        except ModuleNotFoundError as exc:
            payload = {
                "manifest_name": args.single_benchmark,
                "status": "skipped",
                "skip_reason": f"missing_dependency:{exc.name}",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "entries": [],
            }
        except Exception as exc:
            payload = {
                "manifest_name": args.single_benchmark,
                "status": "error",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "traceback": traceback.format_exc(),
                "entries": [],
            }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        print(text)
        if args.output:
            _write_output(args.output, payload)
        return 0

    if args.benchmarks:
        benchmark_names = [
            name.strip() for name in args.benchmarks.split(",") if name.strip()
        ]
    else:
        benchmark_names = [bench.name for bench in load_manifest_benchmarks()]

    rows = []
    script = Path(__file__).resolve()
    for benchmark_name in benchmark_names:
        cmd = [
            sys.executable,
            str(script),
            "--single-benchmark",
            benchmark_name,
            "--samples",
            str(args.samples),
            "--prewarm-runs",
            str(args.prewarm_runs),
            "--bench-time-loops",
            str(args.bench_time_loops),
            "--func-loops",
            str(args.func_loops),
            "--compile-after-n-calls",
            str(args.compile_after_n_calls),
        ]
        if args.specialized_opcodes:
            cmd.append("--specialized-opcodes")
        if args.probe_only:
            cmd.append("--probe-only")

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                rows.append(json.loads(proc.stdout))
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "manifest_name": benchmark_name,
                        "status": "error",
                        "returncode": proc.returncode,
                        "error": f"invalid_json:{exc}",
                        "stdout": proc.stdout,
                        "stderr": proc.stderr,
                        "entries": [],
                    }
                )
            if args.verbose:
                print(f"{benchmark_name}: {rows[-1]['status']}", file=sys.stderr)
            continue

        rows.append(
            {
                "manifest_name": benchmark_name,
                "status": "error",
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "entries": [],
            }
        )
        if args.verbose:
            print(f"{benchmark_name}: error", file=sys.stderr)

    payload = {
        "python": sys.executable,
        "probe_only": args.probe_only,
        "compile_after_n_calls": args.compile_after_n_calls,
        "specialized_opcodes": args.specialized_opcodes,
        "samples": args.samples,
        "prewarm_runs": args.prewarm_runs,
        "bench_time_loops": args.bench_time_loops,
        "func_loops": args.func_loops,
        "benchmarks": rows,
        "summary": _summary(rows),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        _write_output(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
