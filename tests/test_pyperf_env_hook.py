import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "arm"
    / "pyperf_env_hook"
    / "sitecustomize.py"
)


class FakeJit(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("cinderx.jit")
        self.enabled = False
        self.compile_after: int | None = None
        self.specialized = False
        self.jitlist_entries: list[str] = []

    def enable(self) -> None:
        self.enabled = True

    def compile_after_n_calls(self, calls: int) -> None:
        self.compile_after = calls

    def enable_specialized_opcodes(self) -> None:
        self.specialized = True

    def append_jit_list(self, entry: str) -> None:
        self.jitlist_entries.append(entry)


class PyperfEnvHookTests(unittest.TestCase):
    def _run_hook(self, env: dict[str, str]) -> FakeJit:
        fake_jit = FakeJit()
        fake_pkg = types.ModuleType("cinderx")
        fake_pkg.__path__ = []
        fake_pkg.jit = fake_jit

        saved_environ_obj = os.environ
        saved_environ = dict(saved_environ_obj)
        saved_argv = sys.argv
        saved_orig_argv = getattr(sys, "orig_argv", None)
        saved_cinderx = sys.modules.get("cinderx")
        saved_cinderx_jit = sys.modules.get("cinderx.jit")

        try:
            saved_environ_obj.clear()
            saved_environ_obj.update(env)
            sys.argv = ["run_benchmark.py"]
            sys.orig_argv = [
                "/home/test/cinderx/venv/bin/python",
                "-u",
                "run_benchmark.py",
            ]
            sys.modules["cinderx"] = fake_pkg
            sys.modules["cinderx.jit"] = fake_jit

            spec = importlib.util.spec_from_file_location(
                "_pyperf_env_hook_test",
                HOOK_PATH,
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            os.environ = saved_environ_obj
            saved_environ_obj.clear()
            saved_environ_obj.update(saved_environ)
            sys.argv = saved_argv
            if saved_orig_argv is None:
                delattr(sys, "orig_argv")
            else:
                sys.orig_argv = saved_orig_argv
            if saved_cinderx is None:
                sys.modules.pop("cinderx", None)
            else:
                sys.modules["cinderx"] = saved_cinderx
            if saved_cinderx_jit is None:
                sys.modules.pop("cinderx.jit", None)
            else:
                sys.modules["cinderx.jit"] = saved_cinderx_jit

        return fake_jit

    def test_worker_restores_autojit_configuration(self) -> None:
        fake_jit = self._run_hook(
            {
                "PYPERFORMANCE_RUNID": "worker-1",
                "PYTHONJITDISABLE": "1",
                "CINDERX_WORKER_PYTHONJITAUTO": "2",
                "CINDERX_ENABLE_SPECIALIZED_OPCODES": "1",
                "CINDERX_JITLIST_ENTRIES": "alpha,beta",
            }
        )

        self.assertTrue(fake_jit.enabled)
        self.assertEqual(fake_jit.compile_after, 2)
        self.assertTrue(fake_jit.specialized)
        self.assertEqual(fake_jit.jitlist_entries, ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
