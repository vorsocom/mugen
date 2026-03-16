#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run full pre-push quality gates for mugen.

Usage:
  run_prepush_quality_gates.sh [--python <path>] [--mode <full|fast>] [--ephemeral-db|--no-ephemeral-db] [--update-coverage-badge] [--check-coverage-badge]

Options:
  --python <path>          Python interpreter to use (default: python)
  --mode <full|fast>       Gate mode (default: full)
  --ephemeral-db           Start a disposable Postgres instance (default)
  --no-ephemeral-db        Disable disposable Postgres for this run
  --update-coverage-badge  Update README coverage badge after coverage gate
  --check-coverage-badge   Fail if README coverage badge is out of date
  -h, --help               Show this help message

Config resolution order:
  1. MUGEN_TEST_CONFIG_FILE
  2. MUGEN_E2E_CONFIG_FILE
  3. mugen.e2e.toml (repository root)
EOF
}

resolve_test_config_file() {
  if [[ -n "${MUGEN_TEST_CONFIG_FILE:-}" ]]; then
    echo "$MUGEN_TEST_CONFIG_FILE"
    return
  fi

  if [[ -n "${MUGEN_E2E_CONFIG_FILE:-}" ]]; then
    echo "$MUGEN_E2E_CONFIG_FILE"
    return
  fi

  echo "mugen.e2e.toml"
}

find_bin() {
  local name="$1"
  local fallback="${2:-}"
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
    return
  fi
  if [[ -n "$fallback" && -x "$fallback" ]]; then
    echo "$fallback"
    return
  fi
  echo ""
}

setup_ephemeral_db() {
  local initdb_bin
  local pg_ctl_bin
  local createdb_bin

  initdb_bin="$(find_bin initdb /usr/lib/postgresql/16/bin/initdb)"
  pg_ctl_bin="$(find_bin pg_ctl /usr/lib/postgresql/16/bin/pg_ctl)"
  createdb_bin="$(find_bin createdb)"

  if [[ -z "$initdb_bin" || -z "$pg_ctl_bin" || -z "$createdb_bin" ]]; then
    echo "ERROR: --ephemeral-db requires initdb, pg_ctl, and createdb." >&2
    echo "Install PostgreSQL server tools or run with --no-ephemeral-db." >&2
    exit 1
  fi

  EPHEMERAL_INITDB_BIN="$initdb_bin"
  EPHEMERAL_PG_CTL_BIN="$pg_ctl_bin"
  EPHEMERAL_CREATEDB_BIN="$createdb_bin"

  EPHEMERAL_TMP_DIR="$(mktemp -d /tmp/mugen_ephemeral_db_XXXXXX)"
  EPHEMERAL_PGDATA="$EPHEMERAL_TMP_DIR/pgdata"
  EPHEMERAL_LOG="$EPHEMERAL_TMP_DIR/postgres.log"
  EPHEMERAL_CONFIG_FILE="$EPHEMERAL_TMP_DIR/mugen.e2e.toml"
  mkdir -p "$EPHEMERAL_PGDATA"

  "$EPHEMERAL_INITDB_BIN" -D "$EPHEMERAL_PGDATA" -A trust >/dev/null

  EPHEMERAL_PORT=""
  for candidate_port in $(seq 55432 55450); do
    if "$EPHEMERAL_PG_CTL_BIN" \
      -D "$EPHEMERAL_PGDATA" \
      -o "-p $candidate_port -c listen_addresses='' -c unix_socket_directories='/tmp'" \
      -l "$EPHEMERAL_LOG" \
      start >/dev/null 2>&1; then
      EPHEMERAL_PORT="$candidate_port"
      break
    fi
  done

  if [[ -z "$EPHEMERAL_PORT" ]]; then
    echo "ERROR: could not start disposable Postgres (ports 55432-55450)." >&2
    if [[ -f "$EPHEMERAL_LOG" ]]; then
      tail -n 120 "$EPHEMERAL_LOG" >&2 || true
    fi
    exit 1
  fi

  EPHEMERAL_DB_NAME="mugen_e2e_${EPHEMERAL_PORT}_$$"
  "$EPHEMERAL_CREATEDB_BIN" -h /tmp -p "$EPHEMERAL_PORT" "$EPHEMERAL_DB_NAME"

  EPHEMERAL_DB_URL="postgresql+psycopg://$(id -un)@/${EPHEMERAL_DB_NAME}?host=%2Ftmp&port=${EPHEMERAL_PORT}"

  "$PYTHON_BIN" - "$TEST_CONFIG_FILE" "$EPHEMERAL_CONFIG_FILE" "$EPHEMERAL_DB_URL" <<'PY'
import sys

import tomlkit

source_config = sys.argv[1]
target_config = sys.argv[2]
db_url = sys.argv[3]

with open(source_config, "r", encoding="utf8") as handle:
    doc = tomlkit.parse(handle.read())

if "rdbms" not in doc:
    doc["rdbms"] = tomlkit.table()

rdbms = doc["rdbms"]
if "alembic" not in rdbms:
    rdbms["alembic"] = tomlkit.table()
if "sqlalchemy" not in rdbms:
    rdbms["sqlalchemy"] = tomlkit.table()

rdbms["alembic"]["url"] = db_url
rdbms["sqlalchemy"]["url"] = db_url

with open(target_config, "w", encoding="utf8") as handle:
    handle.write(tomlkit.dumps(doc))
PY

  echo "==> Ephemeral DB: $EPHEMERAL_DB_NAME (port $EPHEMERAL_PORT)"
  echo "==> Ephemeral config: $EPHEMERAL_CONFIG_FILE"
  echo "==> Applying migrations on ephemeral DB"
  MUGEN_CONFIG_FILE="$EPHEMERAL_CONFIG_FILE" \
    "$PYTHON_BIN" scripts/run_migration_tracks.py \
      --python "$PYTHON_BIN" \
      --config-file "$EPHEMERAL_CONFIG_FILE" \
      upgrade head

  TEST_CONFIG_FILE="$EPHEMERAL_CONFIG_FILE"
}

teardown_ephemeral_db() {
  if [[ -n "${EPHEMERAL_PG_CTL_BIN:-}" && -n "${EPHEMERAL_PGDATA:-}" && -d "${EPHEMERAL_PGDATA:-}" ]]; then
    "$EPHEMERAL_PG_CTL_BIN" -D "$EPHEMERAL_PGDATA" -m fast stop >/dev/null 2>&1 || true
  fi
  if [[ -n "${EPHEMERAL_TMP_DIR:-}" && -d "${EPHEMERAL_TMP_DIR:-}" ]]; then
    rm -rf "$EPHEMERAL_TMP_DIR" >/dev/null 2>&1 || true
  fi
}

PYTHON_BIN="python"
COVERAGE_BADGE_MODE="skip"
GATE_MODE="full"
USE_EPHEMERAL_DB=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --mode)
      GATE_MODE="$2"
      if [[ "$GATE_MODE" != "full" && "$GATE_MODE" != "fast" ]]; then
        echo "ERROR: --mode must be one of: full, fast" >&2
        exit 1
      fi
      shift 2
      ;;
    --ephemeral-db)
      USE_EPHEMERAL_DB=1
      shift 1
      ;;
    --no-ephemeral-db)
      USE_EPHEMERAL_DB=0
      shift 1
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

TEST_CONFIG_FILE="$(resolve_test_config_file)"

if [[ ! -f "$TEST_CONFIG_FILE" ]]; then
  echo "ERROR: test config not found: $TEST_CONFIG_FILE" >&2
  echo "Set MUGEN_TEST_CONFIG_FILE/MUGEN_E2E_CONFIG_FILE or create mugen.e2e.toml." >&2
  exit 1
fi

trap teardown_ephemeral_db EXIT

if [[ "$USE_EPHEMERAL_DB" -eq 1 ]]; then
  setup_ephemeral_db
fi

echo "==> Runtime config: $TEST_CONFIG_FILE"

echo "==> Coverage gate (100%)"
"$PYTHON_BIN" -m coverage erase
MUGEN_CONFIG_FILE="$TEST_CONFIG_FILE" "$PYTHON_BIN" -m coverage run -m pytest mugen_test -q
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

e2e_suite="full"
if [[ "$GATE_MODE" == "fast" ]]; then
  e2e_suite="smoke"
fi

echo "==> ${e2e_suite^} E2E template validation"
ACP_E2E_PYTHON_BIN="$PYTHON_BIN" \
MUGEN_E2E_CONFIG_FILE="$TEST_CONFIG_FILE" \
MUGEN_CONFIG_FILE="$TEST_CONFIG_FILE" \
bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh \
  --suite "$e2e_suite" \
  --server-mode shared \
  --no-ephemeral-db

echo "All pre-push quality gates passed."
