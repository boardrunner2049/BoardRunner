# Shared by the Table 8 launchers: paths, the boardrunner command, model
# builds and configuration generation. Sourced, not run.

die() { printf 'Error: %s\n' "$*" >&2; exit 2; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }
check_seconds() { [[ $1 =~ ^[1-9][0-9]*$ ]] || die "$2 must be a positive number of seconds, got: $1"; }

scripts_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bundle=$(cd -- "$scripts_dir/.." && pwd)                  # evaluation/fuzzing
repo_root=$(cd -- "$bundle/../.." && pwd)                 # the BoardRunner checkout
examples="$repo_root/examples"

# The four firmware, as in the BoardRunner examples.
declare -A firmware=(
    [mqtt]="$examples/nucleo_h753zi/hybrid/MQTT/firmwares/mqtt_h753.elf"
    [lwip]="$examples/stm32f769i_eval/hybrid/LWIP/firmwares/STM32F769I_EVAL.elf"
    [sdcard]="$examples/stm32f769i_eval/hybrid/SD_Card/firmwares/STM32F769I_EVAL.elf"
    [modbus]="$examples/nucleo_f103rb/hybrid/Modbus/firmwares/STM32F103RB_Modbus.elf"
)
# The baselines' peripheral models: the examples' learned models.
declare -A base_model=(
    [mqtt]="$examples/nucleo_h753zi/hybrid/MQTT/generated_models/usart3_model.c"
    [lwip]="$examples/stm32f769i_eval/hybrid/LWIP/generated_models/ethernet_model.c"
    [sdcard]="$examples/stm32f769i_eval/hybrid/SD_Card/generated_models/sdmmc1_model.c"
    [modbus]="$examples/nucleo_f103rb/hybrid/Modbus/generated_models/usart2_model.c"
)

if [[ -n ${BOARDRUNNER:-} ]]; then
    runner=$BOARDRUNNER
elif command -v boardrunner >/dev/null 2>&1; then
    runner=$(command -v boardrunner)
else
    die "boardrunner is not on PATH; install BoardRunner (README) or set BOARDRUNNER."
fi

# build_model SOURCE OUT_DIR [--pkg fastdyn]: compile one model; prints the .so.
build_model() {
    local source=$1 out_dir=$2; shift 2
    local log="$out_dir/build-models.log"
    mkdir -p "$out_dir"
    "$runner" build-models "$source" -o "$out_dir" "$@" > "$log" 2>&1 ||
        die "Building $source failed; see $log"
    local so="$out_dir/$(basename "${source%.c}").so"
    [[ -f $so ]] || die "Building $source produced no $so; see $log"
    printf '%s\n' "$so"
}

# make_config TEMPLATE OUT RUN_DIR FIRMWARE [MODEL]: fill a template's placeholders.
make_config() {
    local template=$1 out=$2 run_dir=$3 fw=$4 model=${5:-}
    [[ -f $template ]] || die "Missing configuration template: $template"
    [[ -f $fw ]] || die "Missing firmware: $fw"
    sed -e "s|__FIRMWARE__|$fw|g" \
        -e "s|__MAIN_RAM__|$run_dir/ram0|g" \
        -e "s|__RAM1__|$run_dir/ram1|g" \
        -e "s|__QMP_SOCKET__|$run_dir/qmp.sock|g" \
        -e "s|__QEMU_LOG__|$run_dir/qemu.log|g" \
        -e "s|__MODEL_PATH__|$model|g" \
        "$template" > "$out"
}

# new_dir PATH: create a run directory that must not exist yet.
new_dir() {
    [[ ! -e $1 ]] || die "Refusing to reuse an existing directory: $1"
    mkdir -p "$1"
}

# report_bbl FILE LABEL: print the unique basic-block count FastDyn recorded.
report_bbl() {
    if [[ -f $1 ]]; then
        printf '%s basic blocks: %s (%s)\n' "$2" "$(wc -l < "$1")" "$1"
    else
        printf '%s: no basic-block report (%s). FastDyn records coverage only when it is built with a fuzzing backend (-Denable_aflnet=true, see README.md).\n' \
            "$2" "$1" >&2
        return 1
    fi
}
