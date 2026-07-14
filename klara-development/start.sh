#!/usr/bin/env bash
# start.sh - One-command launcher for Klara.
# Responsibilities:
#   - create/update local virtualenv and install Python deps
#   - run deploy checks (Docker, models, voice sample, services)
#   - open chat + live logs together
#   - expose DB admin shortcuts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${SCRIPT_DIR}/klara.pid"
LOG_FILE="${SCRIPT_DIR}/shared-data/logs/klara.log"
PROFILE="${KLARA_PROFILE:-dev}"
TMUX_SESSION="klara"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"
REQUIREMENTS_FILE="${SCRIPT_DIR}/requirements.txt"
DEPS_STAMP="${VENV_DIR}/.deps_installed"
COMMAND="${1:-start}"

if [[ $# -gt 0 ]]; then
    shift
fi

TMUX_STARTED=0

mkdir -p \
    "${SCRIPT_DIR}/shared-data/logs" \
    "${SCRIPT_DIR}/shared-data/sqlite" \
    "${SCRIPT_DIR}/shared-data/vector_db" \
    "${SCRIPT_DIR}/shared-data/voice_samples"

print_help() {
    cat <<EOF
Usage:
  ./start.sh [start|check|logs|db|stop|help] [args...]

Commands:
  start         One-command setup + deploy + chat/log console (default)
  check         Run setup checks only
  logs          Open live log viewer only
  db ...        Run DB admin CLI (status/export/clear/delete/reset)
  stop          Stop a running Klara session
  help          Show this help

Examples:
  ./start.sh
  ./start.sh check
  ./start.sh logs
  ./start.sh db status
  ./start.sh db reset
EOF
}

cleanup() {
    if [[ "${TMUX_STARTED}" == "1" ]]; then
        tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null || true
    fi
}

trap cleanup EXIT

ensure_command() {
    local command_name="$1"
    local hint="${2:-}"
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "❌ Benötigter Befehl fehlt: ${command_name}" >&2
        if [[ -n "${hint}" ]]; then
            echo "   ${hint}" >&2
        fi
        exit 1
    fi
}

ensure_venv() {
    ensure_command python3 "Bitte Python 3.11+ installieren."

    if [[ ! -x "${PYTHON_BIN}" ]]; then
        echo "🐍 Erstelle Python-Venv ..."
        python3 -m venv "${VENV_DIR}"
    fi

    if [[ ! -f "${DEPS_STAMP}" || "${REQUIREMENTS_FILE}" -nt "${DEPS_STAMP}" ]]; then
        echo "📦 Installiere/aktualisiere Python-Abhängigkeiten ..."
        "${PIP_BIN}" install --upgrade pip
        "${PIP_BIN}" install -r "${REQUIREMENTS_FILE}"
        touch "${DEPS_STAMP}"
    fi
}

stop_running_agent() {
    if [[ -f "${PID_FILE}" ]]; then
        local existing_pid
        existing_pid="$(cat "${PID_FILE}")"
        if kill -0 "${existing_pid}" 2>/dev/null; then
            echo "🛑 Stoppe Klara (PID ${existing_pid}) ..."
            kill "${existing_pid}"
            rm -f "${PID_FILE}"
            return 0
        fi
        rm -f "${PID_FILE}"
    fi
    tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null || true
    echo "ℹ️  Keine laufende Klara-Instanz gefunden."
}

ensure_not_running() {
    if [[ -f "${PID_FILE}" ]]; then
        local existing_pid
        existing_pid="$(cat "${PID_FILE}")"
        if kill -0 "${existing_pid}" 2>/dev/null; then
            echo "⚠️  Klara läuft bereits (PID ${existing_pid})."
            echo "   Stoppen mit: ./start.sh stop"
            exit 1
        fi
        rm -f "${PID_FILE}"
    fi
}

run_deploy_command() {
    cd "${SCRIPT_DIR}"
    "${PYTHON_BIN}" deploy.py --profile "${PROFILE}" "$@"
}

run_log_viewer() {
    cd "${SCRIPT_DIR}"
    exec "${PYTHON_BIN}" -m agent.observability.log_viewer --log-file "${LOG_FILE}"
}

run_db_admin() {
    ensure_venv
    cd "${SCRIPT_DIR}"
    exec "${PYTHON_BIN}" -m agent.memory.db_admin --profile "${PROFILE}" "$@"
}

start_tmux_session() {
    tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null || true
    tmux new-session -d -s "${TMUX_SESSION}" \
        -x "$(tput cols 2>/dev/null || echo 220)" \
        -y "$(tput lines 2>/dev/null || echo 50)"

    tmux send-keys -t "${TMUX_SESSION}:0.0" \
        "cd '${SCRIPT_DIR}' && echo \"\$BASHPID\" > '${PID_FILE}' && exec '${PYTHON_BIN}' deploy.py --profile '${PROFILE}' --start" \
        Enter

    tmux split-window -h -t "${TMUX_SESSION}:0.0"
    tmux send-keys -t "${TMUX_SESSION}:0.1" \
        "cd '${SCRIPT_DIR}' && exec '${PYTHON_BIN}' -m agent.observability.log_viewer --log-file '${LOG_FILE}'" \
        Enter

    tmux select-pane -t "${TMUX_SESSION}:0.0"
    TMUX_STARTED=1
    echo "✅ Klara startet jetzt. Links: Setup/Chat | Rechts: Logs"
    tmux attach-session -t "${TMUX_SESSION}" || true
    TMUX_STARTED=0
}

start_plain_mode() {
    echo "💡 tmux nicht gefunden. Starte Chat im aktuellen Terminal."
    echo "   Logs separat mit: ./start.sh logs"
    echo ""
    cd "${SCRIPT_DIR}"
    bash -lc "echo \"\$BASHPID\" > '${PID_FILE}'; exec '${PYTHON_BIN}' deploy.py --profile '${PROFILE}' --start"
}

case "${COMMAND}" in
    start)
        ensure_not_running
        ensure_venv
        if command -v tmux >/dev/null 2>&1; then
            start_tmux_session
        else
            start_plain_mode
        fi
        ;;
    check)
        ensure_venv
        run_deploy_command
        ;;
    logs)
        ensure_venv
        run_log_viewer
        ;;
    db)
        run_db_admin "$@"
        ;;
    stop)
        stop_running_agent
        ;;
    help|-h|--help)
        print_help
        ;;
    *)
        echo "❌ Unbekannter Befehl: ${COMMAND}" >&2
        print_help
        exit 1
        ;;
esac
