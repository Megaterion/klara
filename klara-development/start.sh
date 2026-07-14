#!/usr/bin/env bash
# start.sh - Single-window launcher for Klara
# Prevents duplicate console windows on redeploy.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/klara.pid"
LOG_FILE="${SCRIPT_DIR}/shared-data/logs/klara.log"
PROFILE="${KLARA_PROFILE:-dev}"

mkdir -p "${SCRIPT_DIR}/shared-data/logs"

# --- Cleanup handler ---
cleanup() {
    echo "[start.sh] Shutting down Klara..."
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            wait "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
    echo "[start.sh] Klara stopped."
}

trap cleanup EXIT SIGTERM SIGINT

# --- Check for existing instance ---
if [[ -f "$PID_FILE" ]]; then
    EXISTING_PID=$(cat "$PID_FILE")
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "⚠️  Klara is already running (PID $EXISTING_PID)."
        echo "   To restart: kill $EXISTING_PID and run start.sh again."
        echo "   To force restart: rm ${PID_FILE} && ./start.sh"
        exit 1
    else
        # Stale PID file
        echo "[start.sh] Removing stale PID file."
        rm -f "$PID_FILE"
    fi
fi

echo "🤖 Starting Klara (profile: ${PROFILE})..."
echo "   Log: ${LOG_FILE}"
echo "   PID file: ${PID_FILE}"
echo ""

cd "$SCRIPT_DIR"

# Run agent; write PID file immediately after launch
KLARA_PROFILE="$PROFILE" python -m agent.main &
AGENT_PID=$!
echo "$AGENT_PID" > "$PID_FILE"

echo "✅ Klara started (PID $AGENT_PID)"
echo "   Press Ctrl+C to stop."

# Wait for the agent process; this keeps the shell alive for the trap
wait "$AGENT_PID"
EXIT_CODE=$?

# Cleanup is called by trap; just report exit
if [[ $EXIT_CODE -ne 0 ]]; then
    echo "⚠️  Klara exited with code $EXIT_CODE. Check logs: ${LOG_FILE}"
fi
