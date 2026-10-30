#!/bin/sh
# Developer helper for a SpruceOS device on the network. Runs on the dev machine.
#
#   scripts/device.sh deploy        copy dist/App/Cheevos to the device (run `make package` first)
#   scripts/device.sh launch [GAME] open Cheevos (or one RA game) as PyUI's menus do
#   scripts/device.sh stop          close a launched Cheevos (PyUI comes back)
#   scripts/device.sh running       exit 0 while Cheevos is open, launched or from the menus
#   scripts/device.sh logs          show the app log and the launched session's stderr
#   scripts/device.sh shot FILE     save the device screen as PNG
#   scripts/device.sh press KEY…    tap buttons: up down left right a b x y l1 r1 start select
#                                   (only while Cheevos runs: stops at the first refused tap)
#
# Cheevos runs inside PyUI's process (config.json "pyuiEntry"). "launch" saves the running
# PyUI's environment and command line, asks it to exit, and principal.sh runs
# scripts/device_session.py with PyUI's interpreter: it brings PyUI up again and opens Cheevos
# through PyUI's own runner. Opened from Spruce's menus, Cheevos has no process of its own:
# "running" then looks for PyUI holding the app's log open.
#
# Connection: DEVICE_SSH (full ssh command, e.g. "ssh spruce@192.168.0.105"), or
# DEVICE_HOST (used as "ssh spruce@$DEVICE_HOST").
#
# Safety: the only path this script deletes is $APP_DIR/cheevos (the app's own code).
# Process patterns use the [x] trick so pgrep/pkill never match the remote shell itself.

set -eu

APP_DIR="/mnt/SDCARD/App/Cheevos"
DEV_DIR="/tmp/cheevos-dev"
LOG_FILE="/mnt/SDCARD/Saves/spruce/cheevos-MiyooMini.log"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="/mnt/SDCARD/spruce/miyoomini/bin"

if [ -n "${DEVICE_SSH:-}" ]; then
    SSH="$DEVICE_SSH"
elif [ -n "${DEVICE_HOST:-}" ]; then
    SSH="ssh spruce@$DEVICE_HOST"
else
    echo "Set DEVICE_HOST=<ip> (or DEVICE_SSH='ssh user@ip')" >&2
    exit 2
fi

remote() {
    # shellcheck disable=SC2086  # SSH is a command line by design
    $SSH "$@"
}

# Remote shell test: a launched session runs, or PyUI holds the app's log open (menus).
RUNNING="{ pgrep -f '[c]heevos-dev/session[.]py' >/dev/null || \
    for pid in \$(pgrep -f 'main-ui/[m]ainui[.]py'); do \
        ls -l /proc/\$pid/fd 2>/dev/null | grep -q 'Saves/spruce/cheevos-' && break; false; done; }"

key_code() {
    case "$1" in
        up) echo 103 ;; down) echo 108 ;; left) echo 105 ;; right) echo 106 ;;
        a) echo 57 ;; b) echo 29 ;; x) echo 42 ;; y) echo 56 ;;
        l1) echo 18 ;; r1) echo 20 ;; start) echo 28 ;; select) echo 97 ;;
        *) echo "unknown key: $1" >&2; return 1 ;;
    esac
}

case "${1:-}" in
    deploy)
        [ -d "$REPO/dist/App/Cheevos" ] || { echo "run 'make package' first" >&2; exit 1; }
        remote "rm -rf '$APP_DIR/cheevos' && mkdir -p '$APP_DIR'"
        # ustar without macOS metadata: busybox tar on the device chokes on pax/xattr headers.
        COPYFILE_DISABLE=1 tar -C "$REPO/dist/App/Cheevos" --format ustar -cf - . |
            remote "tar -xf - -C '$APP_DIR' && chmod +x '$APP_DIR/identify-rom.sh' && sync"
        echo "Deployed to $APP_DIR"
        ;;
    launch)
        game=""
        flags="${DEVICE_PYTHON_FLAGS:-}"  # e.g. -X importtime (see .agents/device.md)
        if [ -n "${2:-}" ]; then
            case "$2" in *[!0-9]* | 0*) echo "GAME must be a positive RA game ID" >&2; exit 2 ;; esac
            game=" --game-id $2"
        fi
        # The session script travels on stdin; it is read only once the device is idle. Its path
        # is built from $d, or the idle check's pgrep -f would match this shell's own text.
        remote "
            if $RUNNING; then echo 'Cheevos is already running'; exit 0; fi
            if pgrep -f '[r]a32[.]|[r]etroarch' >/dev/null; then echo 'A game is running; not launching' >&2; exit 1; fi
            pid=\$(pgrep -f 'main-ui/[m]ainui[.]py' | head -n 1)
            [ -n \"\$pid\" ] || { echo 'PyUI is not running: no environment to start from' >&2; exit 1; }
            d='$DEV_DIR'
            mkdir -p \"\$d\" && cat > \"\$d/session.py\"
            cat /proc/\$pid/environ > \"\$d/environ\"
            cat /proc/\$pid/cmdline > \"\$d/cmdline\"
            python=\$(tr '\\0' '\\n' < /proc/\$pid/cmdline | head -n 1)
            printf '%s\\n' \"cd '\$(readlink /proc/\$pid/cwd)'; '\$python' $flags '\$d/session.py'$game 2>'\$d/stderr.log'\" > /tmp/cmd_to_run.sh
            kill -TERM \$pid && echo 'PyUI asked to exit; principal.sh opens Cheevos'
        " <"$REPO/scripts/device_session.py"
        ;;
    stop)
        remote "pkill -TERM -f '[c]heevos-dev/session[.]py' && echo 'Cheevos asked to close; PyUI comes back' || echo 'No launched Cheevos (opened from the menus, press b to close it)'"
        ;;
    running)
        if remote "$RUNNING"; then echo 'Cheevos is running'; else echo 'Cheevos is not running'; exit 1; fi
        ;;
    logs)
        remote "tail -n 60 '$LOG_FILE' 2>/dev/null; echo '--- launched session stderr'; tail -n 30 '$DEV_DIR/stderr.log' 2>/dev/null || true"
        ;;
    shot)
        out="${2:?usage: device.sh shot FILE.png}"
        # The Mini's framebuffer is upside down; Spruce's own screenshot.sh rotates by 180°.
        remote "$BIN/fbgrab -a /tmp/cheevos-shot.png >/dev/null 2>&1 && cat /tmp/cheevos-shot.png && rm -f /tmp/cheevos-shot.png" >"$out"
        if command -v sips >/dev/null 2>&1; then sips -r 180 "$out" >/dev/null; fi
        echo "Saved $out"
        ;;
    press)
        shift
        for key in "$@"; do
            code="$(key_code "$key")"
            # Only ever tap Cheevos: once it exits, taps reach Spruce's menu and can start a game.
            remote "
                $RUNNING || { echo 'Cheevos is not running: not pressing $key' >&2; exit 3; }
                $BIN/send_event /dev/input/event0 $code:1; usleep 80000 2>/dev/null || sleep 1; $BIN/send_event /dev/input/event0 $code:0
            "
            sleep 0.4
        done
        ;;
    *)
        sed -n '2,20p' "$0"
        exit 2
        ;;
esac
