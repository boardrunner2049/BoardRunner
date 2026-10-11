#!/usr/bin/env bash
# flash.sh [firmware.elf|.bin]: flash the MAX78000FTHR through the OpenOCD of
# Analog Devices' MSDK (stock OpenOCD has no MAX78000 support).
# Without an argument it flashes this folder's prebuilt idle firmware.
# MAXIM_PATH is the MSDK installation folder.
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${MAXIM_PATH:?set MAXIM_PATH to the MSDK installation folder}"
OPENOCD="${OPENOCD:-$MAXIM_PATH/Tools/OpenOCD/openocd}"
SCRIPTS="$MAXIM_PATH/Tools/OpenOCD/scripts"
FIRMWARE="${1:-$HERE/idle_firmware_max78000.elf}"

if [ ! -f "$FIRMWARE" ]; then
    echo "error: firmware '$FIRMWARE' not found" >&2
    echo "usage: $0 [firmware.elf|.bin]" >&2
    exit 1
fi

echo "Flashing $FIRMWARE"
if [[ "$FIRMWARE" == *.bin ]]; then
    "$OPENOCD" -s "$SCRIPTS" -f interface/cmsis-dap.cfg -f target/max78000.cfg \
        -c "init; reset halt; program $FIRMWARE 0x10000000 verify reset exit"
else
    "$OPENOCD" -s "$SCRIPTS" -f interface/cmsis-dap.cfg -f target/max78000.cfg \
        -c "init; reset halt; program $FIRMWARE verify reset exit"
fi
echo "Flashed."
