import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import setup


class _DummyCinderXModule:
    def __init__(
        self,
        *,
        import_error: Exception | None = None,
        initialized: bool = True,
    ) -> None:
        self._import_error = import_error
        self._initialized = initialized

    def get_import_error(self) -> Exception | None:
        return self._import_error

    def is_initialized(self) -> bool:
        return self._initialized


class PgoRuntimeValidationTests(unittest.TestCase):
    def test_accepts_initialized_runtime(self) -> None:
        setup.validate_pgo_runtime(_DummyCinderXModule())

    def test_rejects_import_error(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "failed to import",
        ):
            setup.validate_pgo_runtime(
                _DummyCinderXModule(import_error=ImportError("boom"))
            )

    def test_rejects_uninitialized_runtime(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "did not initialize",
        ):
            setup.validate_pgo_runtime(_DummyCinderXModule(initialized=False))


class PgoWorkloadCommandTests(unittest.TestCase):
    def test_defaults_to_cpython_pgo_workload(self) -> None:
        self.assertEqual(setup.get_pgo_workload({}), setup.PGO_WORKLOAD_CPYTHON)

    def test_accepts_custom_command_pgo_workload(self) -> None:
        self.assertEqual(
            setup.get_pgo_workload({"CINDERX_PGO_WORKLOAD": "custom-command"}),
            setup.PGO_WORKLOAD_CUSTOM_COMMAND,
        )

    def test_rejects_unknown_pgo_workload(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Unsupported CINDERX_PGO_WORKLOAD"):
            setup.get_pgo_workload({"CINDERX_PGO_WORKLOAD": "surprise"})

    def test_builds_custom_workload_command(self) -> None:
        cmd = setup.build_custom_pgo_workload_command(
            {"CINDERX_PGO_WORKLOAD_CMD": "python -c 'print(42)'"}
        )

        self.assertEqual(cmd, ["python", "-c", "print(42)"])

    def test_rejects_missing_custom_workload_command(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CINDERX_PGO_WORKLOAD_CMD"):
            setup.build_custom_pgo_workload_command({})

    def test_builds_validating_custom_workload(self) -> None:
        with patch.dict(
            setup.os.environ,
            {
                "CINDERX_PGO_WORKLOAD_CMD": "python -c 'print(42)'",
            },
            clear=False,
        ):
            cmd = setup.build_pgo_workload_command(
                "scratch/temp",
                setup.PGO_WORKLOAD_CUSTOM_COMMAND,
            )

        self.assertEqual(cmd[:2], [setup.sys.executable, "-c"])
        self.assertIn("validate_pgo_runtime", cmd[2])
        self.assertIn("print(42)", cmd[2])


class GccPgoProfileAuditTests(unittest.TestCase):
    def test_collects_profile_counts_for_required_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for target, relative_dir in setup.GCC_PGO_REQUIRED_TARGETS.items():
                target_dir = tmp_path / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / f"{target}.gcda").write_text("", encoding="utf-8")

            counts = setup.collect_gcc_pgo_profile_counts(tmp)

        self.assertEqual(counts, {"_cinderx": 1, "interpreter": 1, "jit": 1})
        setup.require_gcc_pgo_profiles(tmp, counts)

    def test_rejects_when_required_target_has_no_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for target, relative_dir in setup.GCC_PGO_REQUIRED_TARGETS.items():
                if target == "jit":
                    continue
                target_dir = tmp_path / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / f"{target}.gcda").write_text("", encoding="utf-8")

            counts = setup.collect_gcc_pgo_profile_counts(tmp)

            with self.assertRaisesRegex(RuntimeError, "jit"):
                setup.require_gcc_pgo_profiles(tmp, counts)

    def test_allows_missing_first_party_object_profiles_when_required_targets_exist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            for target, relative_dir in setup.GCC_PGO_REQUIRED_TARGETS.items():
                target_dir = tmp_path / relative_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / f"{target}.gcda").write_text("", encoding="utf-8")

            static_python_dir = (
                tmp_path / setup.GCC_PGO_AUDITED_TARGETS["static-python"]
            )
            static_python_dir.mkdir(parents=True, exist_ok=True)
            (static_python_dir / "descrobject_vectorcall.c.o").write_text(
                "",
                encoding="utf-8",
            )

            counts = setup.collect_gcc_pgo_profile_counts(tmp)
            missing_profiles = setup.collect_gcc_pgo_missing_profile_files(
                tmp,
                {"static-python": setup.GCC_PGO_AUDITED_TARGETS["static-python"]},
            )

            self.assertIn("static-python", missing_profiles)
            setup.require_gcc_pgo_profiles(tmp, counts)

    def test_ignores_non_arm_jit_and_dummy_parallel_gc_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            x86_dir = tmp_path / setup.GCC_PGO_AUDITED_TARGETS["jit"] / "cinderx/Jit/codegen/arch"
            x86_dir.mkdir(parents=True, exist_ok=True)
            (x86_dir / "x86_64.cpp.o").write_text("", encoding="utf-8")
            (x86_dir / "unknown.cpp.o").write_text("", encoding="utf-8")

            dummy_parallel_gc_dir = tmp_path / setup.GCC_PGO_AUDITED_TARGETS["parallel-gc"] / "generated"
            dummy_parallel_gc_dir.mkdir(parents=True, exist_ok=True)
            (dummy_parallel_gc_dir / "dummy-parallel-gc.c.o").write_text(
                "",
                encoding="utf-8",
            )

            missing_profiles = setup.collect_gcc_pgo_missing_profile_files(
                tmp,
                {
                    "jit": setup.GCC_PGO_AUDITED_TARGETS["jit"],
                    "parallel-gc": setup.GCC_PGO_AUDITED_TARGETS["parallel-gc"],
                },
            )

        self.assertEqual(missing_profiles, {})


if __name__ == "__main__":
    unittest.main()
