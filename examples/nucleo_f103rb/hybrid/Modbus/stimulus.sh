#!/bin/bash
# Modbus RTU master for the emulated USART2: a pseudo-terminal pair at
# /tmp/usart1_pty (the model's end) and /tmp/host_modbus (ours). After DELAY
# seconds, host/modbus_bridge.py runs its 19 checks REPEAT times against the
# firmware (slave 10) and prints one [OK ] / [FAIL] line per check.
# Needs pymodbus and pyserial (pip install pymodbus pyserial).
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -f /tmp/usart1_pty /tmp/host_modbus
socat PTY,link=/tmp/usart1_pty,raw,echo=0 PTY,link=/tmp/host_modbus,raw,echo=0 &
trap 'kill 0' EXIT
sleep "${DELAY:-5}"
python3 "$HERE/host/modbus_bridge.py" --serial /tmp/host_modbus --repeat "${REPEAT:-1}"
