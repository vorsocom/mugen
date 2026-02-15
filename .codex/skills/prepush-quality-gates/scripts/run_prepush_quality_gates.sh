#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run full pre-push quality gates for mugen.

Usage:
  run_prepush_quality_gates.sh [--python <path>]

Options:
  --python <path>   Python interpreter to use (default: python)
  -h, --help        Show this help message
EOF
}

PYTHON_BIN="python"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: python interpreter not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -f "mugen.toml" ]]; then
  echo "ERROR: mugen.toml not found at repository root." >&2
  echo "Create it from conf/mugen.toml.sample before running this gate." >&2
  exit 1
fi

echo "==> Full unit test suite"
"$PYTHON_BIN" -m pytest mugen_test -q

echo "==> Coverage gate (100%)"
"$PYTHON_BIN" -m coverage erase
"$PYTHON_BIN" -m coverage run -m pytest mugen_test -q
"$PYTHON_BIN" -m coverage report --fail-under=100

echo "==> Full E2E template validation"
bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh

echo "All pre-push quality gates passed."
