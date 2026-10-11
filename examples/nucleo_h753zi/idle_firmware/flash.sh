#!/usr/bin/env bash
# flash.sh [firmware.axf|.elf|.bin]: flash the NUCLEO-H753ZI through OpenOCD.
# Without an argument it flashes this folder's prebuilt idle firmware.
# OPENOCD and BOARD_CFG override the OpenOCD binary and board configuration.
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENOCD="${OPENOCD:-openocd}"
BOARD_CFG="${BOARD_CFG:-board/st_nucleo_h743zi.cfg}"
FIRMWARE="${1:-$HERE/idlefirmware_h7.axf}"

if [ ! -f "$FIRMWARE" ]; then
    echo "error: firmware '$FIRMWARE' not found" >&2
    echo "usage: $0 [firmware.axf|.elf|.bin]" >&2
    exit 1
fi

# No verify: the idle firmware has a .data segment loaded at its RAM address,
# which a verify after reset reads back and rejects.
echo "Flashing $FIRMWARE"
if [[ "$FIRMWARE" == *.bin ]]; then
    "$OPENOCD" -f "$BOARD_CFG" -c "program $FIRMWARE 0x08000000 reset exit"
else
    "$OPENOCD" -f "$BOARD_CFG" -c "program $FIRMWARE reset exit"
fi
echo "Flashed."
