#!/usr/bin/env bash
# Elder (model-only) basic-block baselines of Table 8: each firmware runs with
# the learned model of the peripheral the campaign targets, the rest of the
# hardware on the board (MQTT on a NUCLEO-H753ZI, lwIP and SD-card on an
# STM32F769I-EVAL) or, for Modbus, nothing else and no board.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

usage() {
    cat <<'EOF'
Usage: run_board_coverage.sh {mqtt|lwip|sdcard|modbus} [options]

  --duration SECONDS  wall-clock budget (default: mqtt 25, lwip 65, sdcard 45, modbus 25)
  --work-dir PATH     new directory for the run (default: ./<target>-coverage-<time>)
  --board-port PATH   the board's ST-LINK VCP (mqtt, lwip, sdcard; default: the only one found)
  --broker-host HOST  MQTT broker (mqtt; default 127.0.0.1, started if none answers)
  --broker-port PORT  MQTT broker port (mqtt; default 1883)

The board must run its idle firmware (examples/<board>/idle_firmware/). lwip needs
the host interface tap0 at 192.168.8.1/24 (README.md).
EOF
}

target=${1:-}
case $target in
    mqtt) run_seconds=25 ;;
    lwip) run_seconds=65 ;;
    sdcard) run_seconds=45 ;;
    modbus) run_seconds=25 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
shift
work_dir=
board_port=
broker_host=127.0.0.1
broker_port=1883
while [[ $# -gt 0 ]]; do
    case $1 in
        --duration) [[ $# -ge 2 ]] || die "--duration requires seconds"; run_seconds=$2; shift 2 ;;
        --work-dir) [[ $# -ge 2 ]] || die "--work-dir requires a path"; work_dir=$2; shift 2 ;;
        --board-port) [[ $# -ge 2 ]] || die "--board-port requires a path"; board_port=$2; shift 2 ;;
        --broker-host) [[ $# -ge 2 ]] || die "--broker-host requires a host"; broker_host=$2; shift 2 ;;
        --broker-port) [[ $# -ge 2 ]] || die "--broker-port requires a port"; broker_port=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done
check_seconds "$run_seconds" --duration
require_cmd timeout

detect_board_port() {
    local candidates=() path
    shopt -s nullglob
    for path in /dev/serial/by-id/*; do candidates+=("$(readlink -f -- "$path")"); done
    shopt -u nullglob
    case ${#candidates[@]} in
        1) printf '%s\n' "${candidates[0]}" ;;
        0) die "No board VCP found; connect the board or pass --board-port." ;;
        *) die "Several board VCPs found; pass --board-port." ;;
    esac
}
if [[ $target != modbus ]]; then
    [[ -n $board_port ]] || board_port=$(detect_board_port)
    [[ -c $board_port ]] || die "Board port is not a character device: $board_port"
fi

work_dir=$(realpath -m "${work_dir:-$target-coverage-$(date +%Y%m%d-%H%M%S)}")
new_dir "$work_dir"
# FastDyn's run directory is cleared by `run -o`; the model, configuration and
# the files models open relative to the current directory live next to it.
run_dir="$work_dir/run"
mkdir -p "$run_dir"
model=$(build_model "${base_model[$target]}" "$work_dir/models")
config="$work_dir/${target}_board.toml"
make_config "$bundle/configs/board/$target.toml.in" "$config" "$work_dir" "${firmware[$target]}" "$model"
bbl="$work_dir/bbl.txt"

pids=()
links=()
cleanup() {
    local pid link
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    for link in "${links[@]}"; do [[ -L $link ]] && rm -f -- "$link"; done
}
trap cleanup EXIT

claim_pty() {
    [[ ! -e $1 && ! -L $1 ]] || die "$1 already exists; stop the process using it first."
    links+=("$1")
}

case $target in
    mqtt)
        for cmd in mosquitto mosquitto_pub mosquitto_sub socat; do require_cmd "$cmd"; done
        claim_pty /tmp/usart1_pty
        if ! mosquitto_pub -h "$broker_host" -p "$broker_port" -t fastdyn/probe -m probe >/dev/null 2>&1; then
            mosquitto -p "$broker_port" -v > "$work_dir/mosquitto.log" 2>&1 &
            pids+=($!)
            sleep 1
        fi
        socat -d -d PTY,link=/tmp/usart1_pty,raw,echo=0 TCP:"$broker_host":"$broker_port" > "$work_dir/socat.log" 2>&1 &
        pids+=($!)
        for _ in 1 2 3 4 5; do [[ -L /tmp/usart1_pty ]] && break; sleep 1; done
        [[ -L /tmp/usart1_pty ]] || die "socat did not create /tmp/usart1_pty; see $work_dir/socat.log"
        timeout "$((run_seconds + 5))s" mosquitto_sub -h "$broker_host" -p "$broker_port" -v -t stm32/sensor \
            > "$work_dir/sensor.log" 2> "$work_dir/subscriber.log" &
        pids+=($!)
        (
            sleep 6
            for m in on off on off; do
                mosquitto_pub -h "$broker_host" -p "$broker_port" -t stm32/cmd -m "$m"
                sleep 2
            done
        ) > "$work_dir/publish.log" 2>&1 &
        pids+=($!)
        ;;
    lwip)
        for cmd in ip ping nc curl; do require_cmd "$cmd"; done
        ip link show tap0 >/dev/null 2>&1 || die "tap0 is not configured; see README.md."
        export ETH_TAP=tap0
        (
            sleep 10
            ping -c 1 -W 2 192.168.8.2 || true
            printf 'GET /index.html HTTP/1.0\r\nHost: 192.168.8.2\r\n\r\n' | nc -w 3 192.168.8.2 80 || true
            curl --connect-timeout 3 --max-time 5 http://192.168.8.2/STM32F7xxLED.html >/dev/null || true
            curl --connect-timeout 3 --max-time 5 http://192.168.8.2/missing-page >/dev/null || true
        ) > "$work_dir/traffic.log" 2>&1 &
        pids+=($!)
        ;;
    sdcard)
        for cmd in truncate mkfs.fat; do require_cmd "$cmd"; done
        # The model opens sdcard.img in the current directory.
        truncate -s 64M "$work_dir/sdcard.img"
        mkfs.fat -F 32 "$work_dir/sdcard.img" > "$work_dir/mkfs.log"
        ln -s "$work_dir/sdcard.img" "$run_dir/sdcard.img"
        ;;
    modbus)
        for cmd in socat python3; do require_cmd "$cmd"; done
        claim_pty /tmp/usart1_pty
        claim_pty /tmp/host_modbus
        socat -d -d PTY,link=/tmp/usart1_pty,raw,echo=0 PTY,link=/tmp/host_modbus,raw,echo=0 > "$work_dir/socat.log" 2>&1 &
        pids+=($!)
        for _ in 1 2 3 4 5; do [[ -e /tmp/usart1_pty && -e /tmp/host_modbus ]] && break; sleep 1; done
        [[ -e /tmp/usart1_pty && -e /tmp/host_modbus ]] || die "socat did not create the Modbus PTY pair."
        (
            sleep 6
            python3 "$examples/nucleo_f103rb/hybrid/Modbus/host/modbus_bridge.py" \
                --serial /tmp/host_modbus --profile core --timeout 2
        ) > "$work_dir/modbus-bridge.log" 2>&1 &
        pids+=($!)
        ;;
esac

printf '%s run directory: %s\n' "$target" "$work_dir"
[[ $target == modbus ]] || printf '%s board port: %s\n' "$target" "$board_port"
printf 'The launcher owns a %ss wall-clock budget; its final SIGINT is expected.\n' "$run_seconds"
set +e
(
    cd "$run_dir"
    FASTDYN_COVERAGE=1 FASTDYN_FUZZING=0 FASTDYN_SNAPSHOT_SEGMENTS=all \
        FASTDYN_BBL_FILE="$bbl" FASTDYN_WORK_DIR="$run_dir/fastdyn-work" \
        timeout --signal=INT --kill-after=10s "${run_seconds}s" "$runner" run -c "$config" -o "$run_dir/fastdyn-output"
) > "$work_dir/boardrunner.log" 2>&1
status=$?
set -e
case $status in
    0) printf '%s run ended before its budget.\n' "$target" ;;
    124) printf '%s run reached its %ss budget (expected).\n' "$target" "$run_seconds" ;;
    *) printf '%s run failed with status %s; see %s.\n' "$target" "$status" "$work_dir/boardrunner.log" >&2 ;;
esac
if [[ $target == mqtt ]]; then
    printf 'MQTT sensor messages: %s (%s)\n' "$(wc -l < "$work_dir/sensor.log" 2>/dev/null || echo 0)" "$work_dir/sensor.log"
elif [[ $target == sdcard ]] && strings -a "$work_dir/sdcard.img" | grep -q STM32; then
    printf 'SD-card image contains the firmware output.\n'
fi
report_bbl "$bbl" "$target" || exit 1
[[ $status == 0 || $status == 124 ]] || exit "$status"
