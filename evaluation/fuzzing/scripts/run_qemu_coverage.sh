#!/usr/bin/env bash
# Cold QEMU-only basic-block baseline of the four Table 8 firmware: no
# peripheral model or handler, FastDyn only records coverage.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

usage() {
    cat <<'EOF'
Usage: run_qemu_coverage.sh [all|mqtt|lwip|sdcard|modbus] [--duration SECONDS] [--work-dir PATH]

Runs each firmware with a configuration that has no peripheral model or handler
(all = MQTT, lwIP, SD-card, Modbus). Writes one bbl.txt per target and
summary.tsv into the work directory (default: ./qemu-coverage-<time>).
  --duration SECONDS  per-target wall-clock budget (default 5)
EOF
}

run_seconds=5
work_dir=
selection=all
while [[ $# -gt 0 ]]; do
    case $1 in
        all|mqtt|lwip|sdcard|modbus) selection=$1; shift ;;
        --duration) [[ $# -ge 2 ]] || die "--duration requires seconds"; run_seconds=$2; shift 2 ;;
        --work-dir) [[ $# -ge 2 ]] || die "--work-dir requires a path"; work_dir=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done
check_seconds "$run_seconds" --duration
for cmd in timeout wc sed; do require_cmd "$cmd"; done

work_dir=$(realpath -m "${work_dir:-qemu-coverage-$(date +%Y%m%d-%H%M%S)}")
new_dir "$work_dir"
summary="$work_dir/summary.tsv"
printf 'target\tbasic_blocks\tlauncher_status\tbbl_file\ttoml\n' > "$summary"

declare -A cpu=([mqtt]=cortex-m7 [lwip]=cortex-m7 [sdcard]=cortex-m7 [modbus]=cortex-m3)
declare -A port=([mqtt]=15600 [lwip]=15601 [sdcard]=15602 [modbus]=15603)

run_target() {
    local target=$1
    local dir="$work_dir/$target"
    local config="$dir/qemu-only.toml" bbl="$dir/bbl.txt" status blocks
    mkdir -p "$dir"
    make_config "$bundle/configs/board/qemu_only.toml.in" "$config" "$dir" "${firmware[$target]}"
    sed -i -e "s|__CPU__|${cpu[$target]}|" -e "s|__MONITOR_PORT__|${port[$target]}|" "$config"

    printf '\n[%s] QEMU-only baseline (%ss).\n' "$target" "$run_seconds"
    set +e
    (
        cd "$dir"
        FASTDYN_COVERAGE=1 FASTDYN_FUZZING=0 FASTDYN_SNAPSHOT_SEGMENTS=all FASTDYN_BBL_FILE="$bbl" \
            timeout --signal=INT --kill-after=5s "${run_seconds}s" "$runner" run -c "$config" -o "$dir/fastdyn-output"
    ) > "$dir/boardrunner.log" 2>&1
    status=$?
    set -e

    blocks=0
    [[ -f $bbl ]] && blocks=$(wc -l < "$bbl")
    case $status in
        0) printf '[%s] QEMU exited before the budget.\n' "$target" ;;
        124) printf '[%s] %ss budget reached (expected).\n' "$target" "$run_seconds" ;;
        *) printf '[%s] exited with status %s; see %s.\n' "$target" "$status" "$dir/boardrunner.log" >&2 ;;
    esac
    report_bbl "$bbl" "[$target]" || true
    printf '%s\t%s\t%s\t%s\t%s\n' "$target" "$blocks" "$status" "$bbl" "$config" >> "$summary"
    [[ $status == 0 || $status == 124 ]] && [[ -f $bbl ]]
}

printf 'QEMU-only result directory: %s\n' "$work_dir"
overall=0
targets=(mqtt lwip sdcard modbus)
[[ $selection == all ]] || targets=("$selection")
for t in "${targets[@]}"; do run_target "$t" || overall=1; done

printf '\nQEMU-only coverage summary: %s\n' "$summary"
column -t -s $'\t' "$summary" 2>/dev/null || sed 's/\t/  /g' "$summary"
exit "$overall"
