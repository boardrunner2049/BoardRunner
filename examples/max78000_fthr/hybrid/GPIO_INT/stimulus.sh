#!/bin/bash
# The user button SW1 (P0.2) of the emulated GPIO0 model: characters on the FIFO
# /tmp/max78000_gpio0_pin2 ('0' low, '1' high). SW1 is active low, so each press
# is '0' then '1'; the firmware's interrupt fires on the falling edge.
# Presses it PRESSES times after a few seconds.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
trap 'kill 0' EXIT
F=/tmp/max78000_gpio0_pin2
[ -p "$F" ] || { rm -f "$F"; mkfifo "$F"; }
exec 3<>"$F"
printf 1 >&3
sleep "${DELAY:-8}"
for _ in $(seq "${PRESSES:-5}"); do
    printf 0 >&3; sleep 0.3
    printf 1 >&3; sleep 1
done
