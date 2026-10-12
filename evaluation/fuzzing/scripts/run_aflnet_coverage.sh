#!/usr/bin/env bash
# One of the Table 8 AFLNet campaigns (lwIP, MQTT, Modbus), software only:
# the firmware runs with its fuzzing model, which feeds AFLNet's messages to
# the peripheral; FastDyn records the basic blocks reached.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

usage() {
    cat <<'EOF'
Usage: run_aflnet_coverage.sh {lwip|mqtt|modbus} [new-work-directory]

Needs FastDyn built with AFLNet (-Denable_aflnet=true, README.md). Writes bbl.txt
into the work directory (default: ./<target>-aflnet-<time>). lwIP runs six
phases with saved corpora (55 + 100 + 4 x 60 s) and fails below 2,501 blocks;
MQTT runs 25 s, Modbus 100 s (FASTDYN_AFLNET_RUN_SECONDS overrides).
EOF
}

[[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 2; }
[[ $1 == -h || $1 == --help ]] && { usage; exit 0; }
target=$1
seeds="$bundle/seeds"
case $target in
    lwip) protocol=ETHERNET; corpus="$seeds/lwip/baseline" ;;
    mqtt) protocol=MQTT_CLIENT; corpus="$seeds/mqtt"; default_run_seconds=25 ;;
    modbus) protocol=MODBUS; corpus="$seeds/modbus"; default_run_seconds=100 ;;
    *) usage >&2; exit 2 ;;
esac
corpus=${FASTDYN_AFLNET_CORPUS:-$corpus}
[[ -d $corpus ]] || die "Seed corpus directory does not exist: $corpus"
require_cmd timeout

work_dir=$(realpath -m "${2:-$target-aflnet-$(date +%Y%m%d-%H%M%S)}")
# `run -o` clears the work directory, so the model, the configuration and the
# files the model keeps relative to the current directory are staged beside it.
stage_dir="$work_dir.inputs"
[[ ! -e $work_dir ]] || die "Refusing to reuse an existing directory: $work_dir"
new_dir "$stage_dir"
mkdir -p "$stage_dir/fastdyn_work"     # the MQTT model's snapshot file lives here

model=$(build_model "$bundle/models/${target}_fuzzing_model.c" "$stage_dir/models" --pkg fastdyn)
config="$stage_dir/${target}_aflnet.toml"
make_config "$bundle/configs/aflnet/$target.toml.in" "$config" "$stage_dir" "${firmware[$target]}" "$model"

export FASTDYN_AFLNET_PROTOCOL=$protocol
export FASTDYN_AFLNET_TIMEOUT_MS="${FASTDYN_AFLNET_TIMEOUT_MS:-5000}"
export FASTDYN_AFLNET_NET_TIMEOUT_MS="${FASTDYN_AFLNET_NET_TIMEOUT_MS:-100000000}"
export FASTDYN_AFLNET_WAIT_TIMEOUT_MS="${FASTDYN_AFLNET_WAIT_TIMEOUT_MS:-5000}"
# All writable segments are snapshotted (no interactive range prompt).
export FASTDYN_SNAPSHOT_SEGMENTS="${FASTDYN_SNAPSHOT_SEGMENTS:-all}"
# Modbus's RTU T3.5 timer runs on the snapshot-aware HAL_GetTick hook; a small
# step visits both its pending and expiry paths.
[[ $target == modbus ]] && export FASTDYN_FUZZ_TIME_STEP_MS="${FASTDYN_FUZZ_TIME_STEP_MS:-1}"
# A basic-block campaign: no crash reporter or CPU governor checks.
export AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES="${AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES:-1}"
export AFL_SKIP_CPUFREQ="${AFL_SKIP_CPUFREQ:-1}"

run_campaign() {  # run_campaign SECONDS CORPUS OUT_DIR [extra env...]
    local seconds=$1 input=$2 out=$3; shift 3
    (
        cd "$stage_dir"
        timeout --signal=INT --kill-after=15s "${seconds}s" env "$@" \
            FASTDYN_AFLNET_IN_DIR="$input" \
            FASTDYN_AFLNET_OUT_DIR="$out/aflnet-out" \
            FASTDYN_BBL_FILE="$work_dir/bbl.txt" \
            FASTDYN_WORK_DIR="$out/fastdyn-work" \
            "$runner" run -c "$config" -o "$out"
    )
}

if [[ $target == lwip ]]; then
    baseline_seconds="${FASTDYN_AFLNET_BASELINE_SECONDS:-55}"
    main_seconds="${FASTDYN_AFLNET_MAIN_SECONDS:-100}"
    phase_seconds="${FASTDYN_AFLNET_PHASE_SECONDS:-60}"
    check_seconds "$baseline_seconds" FASTDYN_AFLNET_BASELINE_SECONDS
    check_seconds "$main_seconds" FASTDYN_AFLNET_MAIN_SECONDS
    check_seconds "$phase_seconds" FASTDYN_AFLNET_PHASE_SECONDS
    mkdir -p "$work_dir/corpora" "$work_dir/phases"
    cp -a "$corpus/." "$work_dir/corpora/baseline"
    for phase in all cgi rto ack reassembly; do
        [[ -d $seeds/lwip/$phase ]] || die "Missing saved lwIP $phase corpus: $seeds/lwip/$phase"
        cp -a "$seeds/lwip/$phase/." "$work_dir/corpora/$phase"
    done
    printf 'Multi-phase lwIP campaign in %s\n' "$work_dir"
    # Clean starts that exercise setup, normal traffic, the CGI handler,
    # timers/retransmission, acknowledgements and reassembly; every phase adds
    # to the same bbl.txt.
    for spec in "baseline $baseline_seconds 1000" "all $main_seconds 1000" "cgi $phase_seconds 1000" \
                "rto $phase_seconds 30000" "ack $phase_seconds 1000" "reassembly $phase_seconds 1000"; do
        read -r phase seconds step <<< "$spec"
        printf 'lwIP phase %s (%ss)\n' "$phase" "$seconds"
        set +e
        run_campaign "$seconds" "$work_dir/corpora/$phase" "$work_dir/phases/$phase" \
            FASTDYN_FUZZ_TIME_STEP_MS="$step" > "$work_dir/phases-$phase.log" 2>&1
        status=$?
        set -e
        case $status in
            0|124|130|137) ;;
            *) die "lwIP phase $phase failed with status $status; see $work_dir/phases-$phase.log" ;;
        esac
    done
    report_bbl "$work_dir/bbl.txt" lwIP || exit 1
    (( $(wc -l < "$work_dir/bbl.txt") > 2500 )) ||
        die "lwIP reached at most 2,500 basic blocks; rerun with longer phases in a new directory."
    exit 0
fi

run_seconds="${FASTDYN_AFLNET_RUN_SECONDS:-$default_run_seconds}"
check_seconds "$run_seconds" FASTDYN_AFLNET_RUN_SECONDS
extra=()
if [[ $target == mqtt ]]; then
    # The snapshot must include MQTT's high SRAM stack, not only the ELF's
    # data/BSS. The oscillator shim installs the RCC state SystemInit expects;
    # the IRQ sweep runs the UART handler once before the snapshot.
    extra=(FASTDYN_SNAPSHOT_RANGES_FILE="$bundle/configs/aflnet/mqtt_snapshot_ranges.txt"
           FASTDYN_MQTT_OSC_STARTUP_SHIM="${FASTDYN_MQTT_OSC_STARTUP_SHIM:-1}"
           FASTDYN_MQTT_IRQ_SWEEP="${FASTDYN_MQTT_IRQ_SWEEP:-1}")
fi
printf '%s campaign in %s, %ss (its final SIGINT is the expected cutoff)\n' "$target" "$work_dir" "$run_seconds"
set +e
run_campaign "$run_seconds" "$corpus" "$work_dir" "${extra[@]}" > "$stage_dir/campaign.log" 2>&1
status=$?
set -e
case $status in
    0|124) ;;
    *) printf '%s campaign failed with status %s; see %s.\n' "$target" "$status" "$stage_dir/campaign.log" >&2; exit "$status" ;;
esac
report_bbl "$work_dir/bbl.txt" "$target"
