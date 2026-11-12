#!/bin/bash
#
# start-beacon.sh - Launcher for Harmonic Beacon Spatializer
# (SuperCollider scsynth + sclang + Flask Web UI [+ optional HTTPS tunnel])
#
# Starts full stack in project directory:
#   1. scsynth via pw-jack (PipeWire JACK compat) on UDP 57110
#   2. sclang (offscreen Qt) with beacon.scd (OSC receivers on 57120)
#   3. Flask web UI from ./venv (http://localhost:5050)
#   4. [optional] cloudflared quick-tunnel — gives a public https://
#      URL so phone browsers treat the page as a "secure context"
#      and allow DeviceOrientation / DeviceMotion sensor APIs.
#
# PipeWire provides JACK compatibility (pw-jack), so no separate jackd needed.
# This avoids ALSA exclusive-mode conflicts that break desktop audio.
#
# Proper Ctrl-C / SIGTERM cleanup: kills all tracked child PIDs.
# Usage: ./start-beacon.sh [--live|--file] [--no-https]
#                          [--osc-host HOST] [--osc-port PORT]
#   --live (default): SoundIn.ar(0) from R24 CH1
#   --file:           PlayBuf with harmonic_beacon_2026_05_13_session.wav
#   --no-https:       skip the cloudflared tunnel (LAN-only mode)
#   --osc-host:       accepted OSC source/bind rule (default 127.0.0.1;
#                     use 0.0.0.0 to accept remote dashboards)
#   --osc-port:       sclang OSC listen port (default 57120)
# Environment alternatives: BEACON_OSC_HOST, BEACON_OSC_PORT.
# Requires: pw-jack, scsynth, sclang in PATH + ./venv with flask + python-osc
# Optional: cloudflared at ~/.local/bin/cloudflared (for --no-https bypass)

set -u

# Optional receiving selection; the joint lab uses R24 only.
BEACON_OUTPUT_TARGET="${BEACON_OUTPUT_TARGET:-both}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Parse args. Environment values are defaults so existing deployments can
# configure the listener without changing their launcher invocation.
BEACON_SOURCE="live"
ENABLE_HTTPS=1
BEACON_OSC_HOST="${BEACON_OSC_HOST:-127.0.0.1}"
BEACON_OSC_PORT="${BEACON_OSC_PORT:-57120}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --file)   BEACON_SOURCE="file" ;;
        --live)   BEACON_SOURCE="live" ;;
        --no-https) ENABLE_HTTPS=0 ;;
        --osc-host)
            if [ "$#" -lt 2 ]; then
                echo "[ERROR] --osc-host requires a value" >&2
                exit 2
            fi
            BEACON_OSC_HOST="$2"
            shift
            ;;
        --osc-host=*) BEACON_OSC_HOST="${1#*=}" ;;
        --osc-port)
            if [ "$#" -lt 2 ]; then
                echo "[ERROR] --osc-port requires a value" >&2
                exit 2
            fi
            BEACON_OSC_PORT="$2"
            shift
            ;;
        --osc-port=*) BEACON_OSC_PORT="${1#*=}" ;;
        *)
            echo "[ERROR] Unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done

case "$BEACON_OSC_HOST" in
    ""|*[!A-Za-z0-9._:-]*)
        echo "[ERROR] Invalid OSC host: $BEACON_OSC_HOST" >&2
        exit 2
        ;;
esac
case "$BEACON_OSC_PORT" in
    ""|*[!0-9]*)
        echo "[ERROR] OSC port must be an integer: $BEACON_OSC_PORT" >&2
        exit 2
        ;;
esac
if [ "$BEACON_OSC_PORT" -lt 1 ] || [ "$BEACON_OSC_PORT" -gt 65535 ]; then
    echo "[ERROR] OSC port must be between 1 and 65535: $BEACON_OSC_PORT" >&2
    exit 2
fi
export BEACON_SOURCE BEACON_OSC_HOST BEACON_OSC_PORT

echo "========================================"
echo "  Harmonic Beacon Spatializer"
echo "  Source: $BEACON_SOURCE"
echo "  OSC: $BEACON_OSC_HOST:$BEACON_OSC_PORT"
echo "  HTTPS tunnel: $([ $ENABLE_HTTPS -eq 1 ] && echo 'yes (cloudflared)' || echo 'no  (--no-https)')"
echo "========================================"
echo "Dir: $PROJECT_DIR"
echo ""

# --- 0. Refuse to start if another stack is already running ---
# A second instance cannot bind the OSC/webui ports, but its sclang still
# registers with the running scsynth and spawns an ORPHAN beacon synth that
# sounds over the controllable one — the UI then appears dead (observed
# 2026-09-24). Fail fast instead.
EXISTING=""
for port in "$BEACON_OSC_PORT:udp" "57110:udp" "5050:tcp"; do
    p="${port%:*}"; proto="${port#*:}"
    if [ "$proto" = "udp" ]; then
        holder=$(ss -ulnp 2>/dev/null | awk -v P=":$p\$" '$4 ~ P {print}' | head -1)
    else
        holder=$(ss -tlnp 2>/dev/null | awk -v P=":$p\$" '$4 ~ P {print}' | head -1)
    fi
    [ -n "$holder" ] && EXISTING="$EXISTING\n  $holder"
done
if [ -n "$EXISTING" ]; then
    echo "[ERROR] Another beacon stack appears to be running:" >&2
    echo -e "$EXISTING" >&2
    echo "[ERROR] Ports $BEACON_OSC_PORT/57110/5050 in use. Refusing to start a" >&2
    echo "        second stack (it would spawn an uncontrollable orphan synth)." >&2
    echo "        Stop the running one first: kill its start-beacon.sh, scsynth," >&2
    echo "        sclang and webui.py processes, then re-run." >&2
    exit 3
fi

LOG_DIR="${BEACON_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/beacon-spatial}"
mkdir -p "$LOG_DIR"

SCSYNTH_PID=""
SCLANG_PID=""
WEBUI_PID=""
CFD_PID=""
TUNNEL_URL=""

cleanup() {
    local status="${1:-0}"
    echo ""
    echo "[INFO] Shutdown signal. Stopping children..."
    for pid in "$CFD_PID" "$WEBUI_PID" "$SCLANG_PID" "$SCSYNTH_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 0.6
    for pid in "$CFD_PID" "$WEBUI_PID" "$SCLANG_PID" "$SCSYNTH_PID"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    echo "[OK] All processes stopped."
    exit "$status"
}

trap 'cleanup 0' INT TERM

# --- 1. scsynth via pw-jack (PipeWire) ---
echo "[1/3] scsynth via pw-jack (port 57110, 2in/2out)..."
echo "[INFO] pw-jack scsynth -u 57110 -i 2 -o 2"
pw-jack scsynth -u 57110 -i 2 -o 2 > >(python3 "$PROJECT_DIR/bounded_log.py" "$LOG_DIR/scsynth.log") 2>&1 &
SCSYNTH_PID=$!
echo "      -> PID $SCSYNTH_PID (log: $LOG_DIR/scsynth.log)"
sleep 3

# Apply explicit input/output routes, then verify the actual JACK graph.
# Only links on this newly started SuperCollider client are changed.
if ! python3 "$PROJECT_DIR/beacon_routes.py" --output "$BEACON_OUTPUT_TARGET"; then
    echo "[ERROR] Could not establish the selected R24 audio path" >&2
    cleanup 1
fi

# --- 2. sclang + beacon.scd ---
echo "[2/3] sclang + beacon.scd (mode: $BEACON_SOURCE, OSC: $BEACON_OSC_HOST:$BEACON_OSC_PORT)..."
# sclang needs a pseudo-TTY to stay alive (REPL loop). script(1) provides one.
QT_QPA_PLATFORM=offscreen script -q -c "sclang -u $BEACON_OSC_PORT -d . beacon.scd" /dev/null > >(python3 "$PROJECT_DIR/bounded_log.py" "$LOG_DIR/sclang.log") 2>&1 &
SCLANG_PID=$!
echo "      -> PID $SCLANG_PID (log: $LOG_DIR/sclang.log)"
sleep 8

# --- 3. Flask Web UI from venv ---
echo "[3/3] Flask web UI..."
VENV_PY="$PROJECT_DIR/venv/bin/python3"
if [ ! -x "$VENV_PY" ]; then
    echo "[ERROR] No venv python at $VENV_PY (run: python3 -m venv venv && pip install -r requirements.txt)"
    cleanup 1
fi
$VENV_PY webui.py > >(python3 "$PROJECT_DIR/bounded_log.py" "$LOG_DIR/webui.log") 2>&1 &
WEBUI_PID=$!
echo "      -> PID $WEBUI_PID (log: $LOG_DIR/webui.log)"

# --- 4. [Optional] cloudflared HTTPS tunnel ---
# A LAN-IP http:// page has no "secure context", so phone browsers
# (Android Chrome, iOS Safari) block DeviceOrientation / DeviceMotion.
# The cloudflared quick-tunnel gives a public https:// URL that does
# satisfy the secure-context requirement, so phone sensors work.
if [ $ENABLE_HTTPS -eq 1 ]; then
    CFD_BIN="$HOME/.local/bin/cloudflared"
    if [ ! -x "$CFD_BIN" ]; then
        echo "[WARN] cloudflared not found at $CFD_BIN — skipping HTTPS tunnel."
        echo "       Phone sensors will NOT work over LAN http://."
        echo "       Install with: curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o $CFD_BIN && chmod +x $CFD_BIN"
    else
        echo "[4/4] cloudflared quick-tunnel..."
        # Run cloudflared, capture log, find the URL when ready
        $CFD_BIN tunnel --url http://127.0.0.1:5050 --no-autoupdate > >(python3 "$PROJECT_DIR/bounded_log.py" "$LOG_DIR/cloudflared.log") 2>&1 &
        CFD_PID=$!
        echo "      -> PID $CFD_PID (log: $LOG_DIR/cloudflared.log)"

        # Wait up to 15s for the URL to appear in the log
        for i in $(seq 1 30); do
            TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared.log" 2>/dev/null | head -1 || true)
            if [ -n "$TUNNEL_URL" ]; then
                break
            fi
            sleep 0.5
        done
    fi
fi

# --- Ready ---
echo ""
echo "========================================"
echo "  READY"
echo "========================================"
echo "  Web UI : http://localhost:5050"
echo "  OSC    : $BEACON_OSC_HOST:$BEACON_OSC_PORT (sclang)"
echo "  Server : 127.0.0.1:57110 (scsynth)"
if [ -n "$TUNNEL_URL" ]; then
    echo ""
    echo "  >>> HTTPS TUNNEL (for phone sensors) <<<"
    echo "  >>> $TUNNEL_URL"
    echo "  >>> Open this URL on your phone to enable sensor access."
fi
echo "  Logs   : $LOG_DIR (latest tail, at most1MiB per component)"
echo "========================================"
echo "Press Ctrl-C to stop everything cleanly."
echo ""

wait

# Fallback if children exit on their own
cleanup
