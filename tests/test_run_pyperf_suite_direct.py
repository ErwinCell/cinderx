import argparse
import importlib.util
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "arm"
    / "run_pyperf_suite_direct.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "test_run_pyperf_suite_direct_module",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    saved = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = saved
    return module


class FakeRunner:
    _created = set()

    def __init__(self, *args, **kwargs):
        key = id(self.__class__)
        if key in self.__class__._created:
            raise RuntimeError("runner already created")
        self.__class__._created.add(key)
        self.metadata = {}
        self.argparser = argparse.ArgumentParser()
        self.args = None

    def parse_args(self, args=None):
        parsed = self.argparser.parse_args(args)
        self.args = parsed
        return parsed

    def bench_time_func(self, name, func, *args, **kwargs):
        raise AssertionError("patched method should have been used")

    def bench_func(self, name, func, *args, **kwargs):
        raise AssertionError("patched method should have been used")

    def bench_async_func(self, name, func, *args, **kwargs):
        raise AssertionError("patched method should have been used")

    def bench_command(self, name, command):
        raise AssertionError("patched method should have been used")


class FakeJit(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("cinderx.jit")
        self.enabled = False
        self.compile_after = None
        self.specialized_enabled = False
        self.specialized_disabled = False

    def enable(self) -> None:
        self.enabled = True

    def compile_after_n_calls(self, calls: int) -> None:
        self.compile_after = calls

    def enable_specialized_opcodes(self) -> None:
        self.specialized_enabled = True

    def disable_specialized_opcodes(self) -> None:
        self.specialized_disabled = True

    def get_and_clear_runtime_stats(self):
        return {"deopt": []}


class RunPyperfSuiteDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.saved_modules = {}

    def tearDown(self) -> None:
        for name, value in self.saved_modules.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value

    def _install_module(self, name: str, value: object) -> None:
        self.saved_modules.setdefault(name, sys.modules.get(name))
        sys.modules[name] = value

    def test_capture_entries_uses_manifest_argv(self) -> None:
        fake_pyperf = types.ModuleType("pyperf")
        fake_pyperf.Runner = FakeRunner
        self._install_module("pyperf", fake_pyperf)

        with tempfile.TemporaryDirectory() as td:
            runscript = Path(td) / "run_benchmark.py"
            runscript.write_text(
                textwrap.dedent(
                    """
                    import pyperf

                    def bench_scale(loops, scale):
                        return loops * scale

                    if __name__ == "__main__":
                        runner = pyperf.Runner()
                        runner.argparser.add_argument("--scale", type=int, default=3)
                        args = runner.parse_args()
                        runner.metadata["description"] = "demo"
                        runner.bench_time_func("demo_scale", bench_scale, args.scale)
                    """
                ),
                encoding="utf-8",
            )

            entries = self.module.capture_entries(str(runscript), ["--scale", "7"])

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, "bench_time_func")
        self.assertEqual(entries[0].name, "demo_scale")
        self.assertEqual(entries[0].args, (7,))
        self.assertEqual(entries[0].metadata["description"], "demo")

    def test_run_entry_restores_autojit_settings(self) -> None:
        fake_jit = FakeJit()
        fake_cinderx = types.ModuleType("cinderx")
        fake_cinderx.__path__ = []
        fake_cinderx.jit = fake_jit
        self._install_module("cinderx", fake_cinderx)
        self._install_module("cinderx.jit", fake_jit)

        calls = []

        def workload(value):
            calls.append(value)
            return value * 2

        entry = self.module.CapturedEntry(
            kind="bench_func",
            name="demo_func",
            target=workload,
            args=(5,),
            kwargs={},
            metadata={},
        )

        result = self.module.run_entry(
            entry,
            compile_after_n_calls=2,
            specialized_opcodes=True,
            prewarm_runs=2,
            samples=3,
            bench_time_loops=1,
            func_loops=1,
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(fake_jit.enabled)
        self.assertEqual(fake_jit.compile_after, 2)
        self.assertTrue(fake_jit.specialized_enabled)
        self.assertEqual(len(result["samples"]), 3)
        self.assertEqual(calls, [5, 5, 5, 5, 5])

    def test_probe_only_marks_command_benchmarks_skipped(self) -> None:
        fake_pyperf = types.ModuleType("pyperf")
        fake_pyperf.Runner = FakeRunner
        self._install_module("pyperf", fake_pyperf)

        with tempfile.TemporaryDirectory() as td:
            runscript = Path(td) / "run_benchmark.py"
            runscript.write_text(
                textwrap.dedent(
                    """
                    import pyperf

                    if __name__ == "__main__":
                        runner = pyperf.Runner()
                        runner.parse_args()
                        runner.bench_command("python_startup", ["python", "-c", "pass"])
                    """
                ),
                encoding="utf-8",
            )

            fake_benchmark = types.SimpleNamespace(
                name="python_startup",
                runscript=str(runscript),
                extra_opts=[],
                tags=["startup"],
            )
            saved = self.module.resolve_manifest_benchmark
            try:
                self.module.resolve_manifest_benchmark = lambda name: fake_benchmark
                result = self.module.run_manifest_benchmark(
                    "python_startup",
                    compile_after_n_calls=2,
                    specialized_opcodes=False,
                    prewarm_runs=0,
                    samples=1,
                    bench_time_loops=1,
                    func_loops=1,
                    probe_only=True,
                )
            finally:
                self.module.resolve_manifest_benchmark = saved

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["entries"][0]["kind"], "bench_command")
        self.assertEqual(result["entries"][0]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
