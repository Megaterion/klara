#!/usr/bin/env bash
# start.sh - Two-window launcher for Klara
# Uses tmux to show a chat window and a separate log window side-by-side.
# Falls back to a single terminal if tmux is not available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/klara.pid"
LOG_FILE="${SCRIPT_DIR}/shared-data/logs/klara.log"
PROFILE="${KLARA_PROFILE:-dev}"
TMUX_SESSION="klara"

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
    # Kill tmux session if we created it
    if [[ "${_KLARA_TMUX_OWNER:-}" == "1" ]]; then
        tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
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
        echo "[start.sh] Removing stale PID file."
        rm -f "$PID_FILE"
    fi
fi

echo "🤖 Starting Klara (profile: ${PROFILE})..."
echo "   Log: ${LOG_FILE}"
echo "   PID file: ${PID_FILE}"
echo ""

cd "$SCRIPT_DIR"

# ------------------------------------------------------------------ #
#  Two-window mode via tmux                                           #
# ------------------------------------------------------------------ #
if command -v tmux &>/dev/null && [[ -z "${KLARA_NO_TMUX:-}" ]]; then
    # Kill stale session if it exists
    tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

    export _KLARA_TMUX_OWNER=1

    # Create detached session; first window = chat
    tmux new-session -d -s "$TMUX_SESSION" \
        -x "$(tput cols 2>/dev/null || echo 220)" \
        -y "$(tput lines 2>/dev/null || echo 50)"

    # Left pane: Klara agent (chat UI)
    tmux send-keys -t "${TMUX_SESSION}:0" \
        "cd '$SCRIPT_DIR' && KLARA_PROFILE='$PROFILE' python -m agent.main; echo '[Chat beendet — Fenster schließt in 5s]'; sleep 5" \
        Enter

    # Right pane: log viewer
    tmux split-window -h -t "${TMUX_SESSION}:0"
    tmux send-keys -t "${TMUX_SESSION}:0" \
        "cd '$SCRIPT_DIR' && python -m agent.observability.log_viewer --log-file '$LOG_FILE'; echo '[Log-Viewer beendet]'; sleep 5" \
        Enter

    # Focus left pane (chat)
    tmux select-pane -t "${TMUX_SESSION}:0.0"

    echo "✅ Klara gestartet in tmux-Session '${TMUX_SESSION}'"
    echo "   Linkes Fenster: Chat  |  Rechtes Fenster: Logs"
    echo "   Beenden: Ctrl+C in diesem Terminal oder 'tmux kill-session -t ${TMUX_SESSION}'"
    echo ""

    # Attach and wait
    tmux attach-session -t "$TMUX_SESSION"

# ------------------------------------------------------------------ #
#  Single-window fallback (no tmux)                                  #
# ------------------------------------------------------------------ #
else
    echo "💡 Tipp: Installiere tmux für automatische Zwei-Fenster-Ansicht."
    echo "   Log-Viewer in einem zweiten Terminal starten:"
    echo "     cd '${SCRIPT_DIR}' && python -m agent.observability.log_viewer"
    echo ""

    KLARA_PROFILE="$PROFILE" python -m agent.main &
    AGENT_PID=$!
    echo "$AGENT_PID" > "$PID_FILE"

    echo "✅ Klara started (PID $AGENT_PID)"
    echo "   Press Ctrl+C to stop."

    wait "$AGENT_PID"
    EXIT_CODE=$?

    if [[ $EXIT_CODE -ne 0 ]]; then
        echo "⚠️  Klara exited with code $EXIT_CODE. Check logs: ${LOG_FILE}"
    fi
fi
