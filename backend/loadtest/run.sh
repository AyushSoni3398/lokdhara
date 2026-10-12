#!/usr/bin/env bash
# Runs the load test against a local API, worker, and a separate _loadtest database
# (docs/LOAD_TESTING.md). Synthetic data only; nothing leaves this machine.
#
#   docker compose -f infra/docker-compose.yml up -d db     # from the repository root
#   bash backend/loadtest/run.sh [users] [duration]         # defaults: 50 users, 5m
#
# Settings (environment): SPAWN_RATE (users started per second, 5), API_WORKERS (uvicorn
# processes, 2), KEEP_ALIVE (seconds uvicorn keeps idle connections open, 75; see
# docs/DEPLOYMENT.md), API_CPUS and LOCUST_CPUS (cores to pin to with taskset on Linux; by default
# the API gets 2 cores, like the pilot VM), LKD_DATABASE_URL (the server to use; the database
# name is replaced with lokdhara_loadtest).
set -euo pipefail
cd "$(dirname "$0")/.."

USERS=${1:-50}
DURATION=${2:-5m}
SPAWN_RATE=${SPAWN_RATE:-5}
API_WORKERS=${API_WORKERS:-2}
KEEP_ALIVE=${KEEP_ALIVE:-75}
API_CPUS=${API_CPUS:-0,1}
LOCUST_CPUS=${LOCUST_CPUS:-2,3}
PORT=8010
SERVER_URL=${LKD_DATABASE_URL:-postgresql+psycopg://lokdhara:lokdhara@localhost:5432/lokdhara}
RESULTS=loadtest/results

export LKD_ENV=development
export LKD_DATABASE_URL="${SERVER_URL%/*}/lokdhara_loadtest"
export LKD_LOG_LEVEL=WARNING
# Each simulated user uploads far more often than the real 60-an-hour limit allows.
export LKD_UPLOADS_PER_USER_PER_HOUR=1000000
LKD_LOCAL_STORAGE_DIR=$(mktemp -d)
export LKD_LOCAL_STORAGE_DIR

# CPU pinning prefixes (Linux only). Commands run directly, so `$!` is the process itself.
PIN_API=()
PIN_LOCUST=()
if command -v taskset >/dev/null; then
  if [[ -n "$API_CPUS" ]]; then PIN_API=(taskset -c "$API_CPUS"); fi
  if [[ -n "$LOCUST_CPUS" ]]; then PIN_LOCUST=(taskset -c "$LOCUST_CPUS"); fi
fi

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$LKD_LOCAL_STORAGE_DIR"  # the synthetic uploads
}
trap cleanup EXIT

mkdir -p "$RESULTS"
uv sync --group loadtest -q
# Started directly, not through `uv run`, so stopping them at the end reaches the processes.
PY=.venv/bin/python
$PY -m loadtest.prepare --users "$USERS"

${PIN_API[@]+"${PIN_API[@]}"} $PY -m uvicorn app.main:app --port "$PORT" \
  --workers "$API_WORKERS" --timeout-keep-alive "$KEEP_ALIVE" --log-level warning \
  --no-access-log >"$RESULTS/api.log" 2>&1 &
pids+=($!)
${PIN_API[@]+"${PIN_API[@]}"} $PY -m app.worker >"$RESULTS/worker.log" 2>&1 &
pids+=($!)
$PY -m loadtest.monitor --out "$RESULTS/queue.csv" &
pids+=($!)

for _ in $(seq 1 60); do
  curl -sf "http://localhost:$PORT/healthz" >/dev/null && break
  sleep 1
done

${PIN_LOCUST[@]+"${PIN_LOCUST[@]}"} $PY -m locust -f loadtest/locustfile.py --headless \
  --users "$USERS" --spawn-rate "$SPAWN_RATE" --run-time "$DURATION" \
  --host "http://localhost:$PORT" --csv "$RESULTS/run" --csv-full-history --only-summary

echo "Results: $RESULTS/run_stats.csv, run_failures.csv, run_stats_history.csv, queue.csv"
echo "Uploaded bytes on disk at the end: $(du -sh "$LKD_LOCAL_STORAGE_DIR" | cut -f1)"
