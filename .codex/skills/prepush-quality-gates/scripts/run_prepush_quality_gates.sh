#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run full pre-push quality gates for mugen.

Usage:
  run_prepush_quality_gates.sh [--python <path>] [--update-coverage-badge] [--check-coverage-badge]

Options:
  --python <path>          Python interpreter to use (default: python)
  --update-coverage-badge  Update README coverage badge after coverage gate
  --check-coverage-badge   Fail if README coverage badge is out of date
  -h, --help               Show this help message
EOF
}

PYTHON_BIN="python"
COVERAGE_BADGE_MODE="skip"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --update-coverage-badge)
      if [[ "$COVERAGE_BADGE_MODE" == "check" ]]; then
        echo "ERROR: --update-coverage-badge cannot be combined with --check-coverage-badge." >&2
        exit 1
      fi
      COVERAGE_BADGE_MODE="write"
      shift 1
      ;;
    --check-coverage-badge)
      if [[ "$COVERAGE_BADGE_MODE" == "write" ]]; then
        echo "ERROR: --check-coverage-badge cannot be combined with --update-coverage-badge." >&2
        exit 1
      fi
      COVERAGE_BADGE_MODE="check"
      shift 1
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

coverage_total="$("$PYTHON_BIN" -m coverage report --format=total)"
if [[ ! "$coverage_total" =~ ^[0-9]+$ ]]; then
  echo "ERROR: could not parse coverage total from coverage report." >&2
  exit 1
fi

if [[ "$COVERAGE_BADGE_MODE" == "write" ]]; then
  echo "==> Update README coverage badge"
  "$PYTHON_BIN" scripts/update_coverage_badge.py --coverage "$coverage_total"
elif [[ "$COVERAGE_BADGE_MODE" == "check" ]]; then
  echo "==> Validate README coverage badge"
  "$PYTHON_BIN" scripts/update_coverage_badge.py --coverage "$coverage_total" --check
fi

echo "==> Full E2E template validation"
ACP_E2E_PYTHON_BIN="$PYTHON_BIN" bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh

echo "All pre-push quality gates passed."
