#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="${SOURCE_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PYTHON="${PYTHON:-/home/pybin/bin/python3.14}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$SOURCE_ROOT/artifacts/pgo_lto_pyperf_$RUN_ID}"
WORK_ROOT="${WORK_ROOT:-/tmp/cinderx-pgo-lto-pyperf-$RUN_ID}"
THRESHOLD="${THRESHOLD:-1.02}"
JIT_LIST_FILE="${PYTHONJITLISTFILE:-/home/jit_list.txt}"
PYPERF_INHERIT_ENV="${PYPERF_INHERIT_ENV:-http_proxy,https_proxy,LD_LIBRARY_PATH,PYTHONJITAUTO,PYTHONJITSPECIALIZEDOPCODES,PYTHONJITLISTFILE,PYTHONJITENABLEJITLISTWILDCARDS,PYTHONJITENABLEHIRINLINER,PYTHONJITTYPEANNOTATIONGUARDS}"
PGO_TRAINING_INHERIT_ENV="${PGO_TRAINING_INHERIT_ENV:-http_proxy,https_proxy,LD_LIBRARY_PATH,LLVM_PROFILE_FILE,PYTHONPATH,PYTHONJITAUTO,PYTHONJITSPECIALIZEDOPCODES,PYTHONJITLISTFILE,PYTHONJITENABLEJITLISTWILDCARDS,PYTHONJITENABLEHIRINLINER,PYTHONJITTYPEANNOTATIONGUARDS}"

BASELINE_SRC="$WORK_ROOT/baseline-src"
CANDIDATE_SRC="$WORK_ROOT/pgo-lto-src"
BASELINE_JSON="$ARTIFACT_DIR/baseline.json"
CANDIDATE_JSON="$ARTIFACT_DIR/pgo_lto.json"
COMPARE_TXT="$ARTIFACT_DIR/compare.txt"
SUMMARY_JSON="$ARTIFACT_DIR/speedup_summary.json"

copy_source() {
  local dest="$1"
  mkdir -p "$dest"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude .git \
      --exclude artifacts \
      --exclude build \
      --exclude cmake-build-debug \
      --exclude dist \
      --exclude scratch \
      --exclude __pycache__ \
      "$SOURCE_ROOT/" "$dest/"
  else
    (cd "$SOURCE_ROOT" && tar \
      --exclude .git \
      --exclude artifacts \
      --exclude build \
      --exclude cmake-build-debug \
      --exclude dist \
      --exclude scratch \
      --exclude __pycache__ \
      -cf - .) | (cd "$dest" && tar -xf -)
  fi
}

shell_quote_command() {
  local quoted=""
  printf -v quoted "%q " "$@"
  printf "%s" "${quoted% }"
}

build_pgo_training_cmd() {
  if [[ -n "${CINDERX_PGO_WORKLOAD_CMD:-}" ]]; then
    printf "%s" "$CINDERX_PGO_WORKLOAD_CMD"
    return
  fi

  local training_args=()
  if [[ -n "${PGO_TRAINING_ARGS:-}" ]]; then
    read -r -a training_args <<< "$PGO_TRAINING_ARGS"
  else
    training_args=(--affinity=2 --warmup 3)
  fi

  shell_quote_command \
    "$PYTHON" -m pyperformance run \
    "${training_args[@]}" \
    --inherit-environ "$PGO_TRAINING_INHERIT_ENV" \
    -o "$ARTIFACT_DIR/pgo_training.json"
}

build_install() {
  local src="$1"
  local label="$2"
  local enable_pgo="$3"
  local enable_lto="$4"
  local log="$ARTIFACT_DIR/${label}_build.log"

  echo ">> build/install $label"
  (
    cd "$src"
    env \
      CINDERX_ENABLE_PGO="$enable_pgo" \
      CINDERX_ENABLE_LTO="$enable_lto" \
      CINDERX_BUILD_JOBS="${CINDERX_BUILD_JOBS:-$(nproc)}" \
      "$PYTHON" -m pip install -v .
  ) 2>&1 | tee "$log"
}

build_install_pgo_lto() {
  local src="$1"
  local log="$ARTIFACT_DIR/pgo_lto_build.log"
  local hook_dir="$src/scripts/arm/pyperf_env_hook"
  local workload_cmd
  workload_cmd="$(build_pgo_training_cmd)"

  echo ">> build/install pgo_lto"
  (
    cd "$src"
    env \
      PYTHONPATH="$hook_dir${PYTHONPATH:+:$PYTHONPATH}" \
      CINDERX_ENABLE_PGO=1 \
      CINDERX_ENABLE_LTO=1 \
      CINDERX_BUILD_JOBS="${CINDERX_BUILD_JOBS:-$(nproc)}" \
      CINDERX_PGO_WORKLOAD=custom-command \
      CINDERX_PGO_WORKLOAD_CMD="$workload_cmd" \
      "$PYTHON" -m pip install -v .
  ) 2>&1 | tee "$log"
}

run_pyperformance() {
  local output_json="$1"
  local label="$2"
  local log="$ARTIFACT_DIR/${label}_pyperformance.log"

  echo ">> pyperformance $label"
  env \
    PYTHONJITTYPEANNOTATIONGUARDS="${PYTHONJITTYPEANNOTATIONGUARDS:-1}" \
    PYTHONJITENABLEJITLISTWILDCARDS="${PYTHONJITENABLEJITLISTWILDCARDS:-1}" \
    PYTHONJITENABLEHIRINLINER="${PYTHONJITENABLEHIRINLINER:-1}" \
    PYTHONJITAUTO="${PYTHONJITAUTO:-2}" \
    PYTHONJITSPECIALIZEDOPCODES="${PYTHONJITSPECIALIZEDOPCODES:-1}" \
    PYTHONJITLISTFILE="$JIT_LIST_FILE" \
    "$PYTHON" -m pyperformance run \
      --affinity=2 \
      --warmup 3 \
      --inherit-environ "$PYPERF_INHERIT_ENV" \
      -o "$output_json" \
      2>&1 | tee "$log"
}

mkdir -p "$ARTIFACT_DIR" "$WORK_ROOT"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: missing python executable: $PYTHON" >&2
  exit 2
fi
if [[ ! -f "$JIT_LIST_FILE" ]]; then
  echo "ERROR: missing PYTHONJITLISTFILE: $JIT_LIST_FILE" >&2
  exit 2
fi

echo "source_root=$SOURCE_ROOT"
echo "artifact_dir=$ARTIFACT_DIR"
echo "work_root=$WORK_ROOT"
echo "python=$PYTHON"
echo "threshold=$THRESHOLD"

copy_source "$BASELINE_SRC"
copy_source "$CANDIDATE_SRC"

build_install "$BASELINE_SRC" baseline 0 0
run_pyperformance "$BASELINE_JSON" baseline

build_install_pgo_lto "$CANDIDATE_SRC"
run_pyperformance "$CANDIDATE_JSON" pgo_lto

echo ">> pyperformance compare"
"$PYTHON" -m pyperformance compare -O table "$BASELINE_JSON" "$CANDIDATE_JSON" \
  2>&1 | tee "$COMPARE_TXT"

echo ">> geometric mean speedup"
"$PYTHON" "$SOURCE_ROOT/scripts/arm/pyperf_speedup_summary.py" \
  --baseline "$BASELINE_JSON" \
  --changed "$CANDIDATE_JSON" \
  --output "$SUMMARY_JSON" \
  --threshold "$THRESHOLD"

echo "artifacts=$ARTIFACT_DIR"
