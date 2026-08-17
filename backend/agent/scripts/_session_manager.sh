#!/bin/bash
# Concurrent paper session manager.
# Usage:
#   ./_session_manager.sh start <session_dir> [--poll N]
#   ./_session_manager.sh stop  <tmux_session_name>
#   ./_session_manager.sh restart <session_dir> [--poll N]
#   ./_session_manager.sh list
#   ./_session_manager.sh logs  <tmux_session_name> [lines]
#   ./_session_manager.sh stop-all

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$(realpath "$AGENT_DIR/../.venv")"
PYTHON="$VENV/bin/python"
POLL_SECONDS=60

usage() {
    echo "Usage: $0 {start|restart} <session_dir> [--poll N] | stop <tmux_name> | stop-all | list | logs <tmux_name> [lines]" >&2
    exit 1
}

detect_command() {
    local session_dir="$1"
    local session_json="$session_dir/session.json"
    if [[ ! -f "$session_json" ]]; then
        echo "ERROR: session.json not found in $session_dir" >&2
        exit 1
    fi
    local strategy
    strategy="$($PYTHON -c "import json,sys; print(json.load(open(sys.argv[1])).get('strategy_type','periodic_equal_weight_rebalance'))" "$session_json")"
    if [[ "$strategy" == *"funding"* ]]; then
        echo "run-funding"
    else
        echo "run"
    fi
}

do_start() {
    local session_dir="$1"
    local poll="${2:-$POLL_SECONDS}"
    local abs_dir
    abs_dir="$(cd "$AGENT_DIR" && realpath "$session_dir")"
    local name
    name="$(basename "$abs_dir")"
    local cmd
    cmd="$(detect_command "$abs_dir")"

    if tmux has-session -t "$name" 2>/dev/null; then
        echo "Session '$name' is already running. Use 'stop' or 'restart'." >&2
        exit 1
    fi

    echo "Starting $name (strategy: $cmd, poll: ${poll}s)"
    tmux new-session -d -s "$name" \
        "cd '$AGENT_DIR' && '$PYTHON' paper_session.py $cmd --session-dir '$abs_dir' --poll-seconds $poll"
    echo "Started tmux session '$name'"
    tmux list-sessions -F "#{session_name} | #{session_created}"
}

do_stop() {
    local name="$1"
    if ! tmux has-session -t "$name" 2>/dev/null; then
        echo "No tmux session named '$name'" >&2
        exit 1
    fi
    echo "Stopping tmux session '$name'"
    tmux kill-session -t "$name"
}

do_restart() {
    local session_dir="$1"
    local poll="${2:-$POLL_SECONDS}"
    local abs_dir
    abs_dir="$(cd "$AGENT_DIR" && realpath "$session_dir")"
    local name
    name="$(basename "$abs_dir")"
    if tmux has-session -t "$name" 2>/dev/null; then
        echo "Stopping existing session '$name'"
        tmux kill-session -t "$name" || true
    fi
    do_start "$session_dir" "$poll"
}

do_list() {
    if tmux list-sessions 2>/dev/null; then
        :
    else
        echo "No tmux sessions running."
    fi
}

do_logs() {
    local name="$1"
    local lines="${2:-50}"
    if ! tmux has-session -t "$name" 2>/dev/null; then
        echo "No tmux session named '$name'" >&2
        exit 1
    fi
    tmux capture-pane -p -t "$name" | tail -n "$lines"
}

do_stop_all() {
    echo "WARNING: stopping all tmux sessions and any paper_session.py processes."
    tmux list-sessions -F '#S' 2>/dev/null | xargs -r -n1 tmux kill-session -t 2>/dev/null || true
    pkill -f 'paper_session.py' 2>/dev/null || true
    echo "All paper sessions stopped."
}

# Parse optional --poll for start/restart before the command
PARSE_POLL=true
POLL="$POLL_SECONDS"

if [[ $# -lt 1 ]]; then
    usage
fi

COMMAND="$1"
shift

# If first arg after command is a flag, handle it; otherwise treat session_dir as first
SESSION_DIR=""
if [[ $# -ge 1 && "$1" != --* ]]; then
    SESSION_DIR="$1"
    shift
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --poll)
            POLL="$2"
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

case "$COMMAND" in
    start)
        [[ -n "$SESSION_DIR" ]] || usage
        do_start "$SESSION_DIR" "$POLL"
        ;;
    restart)
        [[ -n "$SESSION_DIR" ]] || usage
        do_restart "$SESSION_DIR" "$POLL"
        ;;
    stop)
        [[ -n "$SESSION_DIR" ]] || usage
        do_stop "$SESSION_DIR"
        ;;
    stop-all)
        do_stop_all
        ;;
    list)
        do_list
        ;;
    logs)
        [[ -n "$SESSION_DIR" ]] || usage
        # SESSION_DIR holds tmux name; remaining arg already parsed as --poll? Logs doesn't take --poll.
        # If user passed a number after name, it was consumed by --poll parser. Need special handling.
        do_logs "$SESSION_DIR" "$POLL"
        ;;
    *)
        usage
        ;;
esac
