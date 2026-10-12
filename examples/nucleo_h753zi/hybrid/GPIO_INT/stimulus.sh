#!/bin/bash
# The user button (PC13) of the emulated GPIOC model: characters on the FIFO
# /tmp/gpioc_pc13 ('0' low, '1' high; the EXTI model fires on the rising edge).
# Presses it PRESSES times after a few seconds, a couple of seconds apart, so
# each change of the LED blink rate can be seen.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
trap 'kill 0' EXIT
[ -p /tmp/gpioc_pc13 ] || { rm -f /tmp/gpioc_pc13; mkfifo /tmp/gpioc_pc13; }
exec 3<>/tmp/gpioc_pc13
sleep "${DELAY:-4}"
for _ in $(seq "${PRESSES:-3}"); do
    printf 0 >&3; sleep 0.3
    printf 1 >&3; sleep 2
done
