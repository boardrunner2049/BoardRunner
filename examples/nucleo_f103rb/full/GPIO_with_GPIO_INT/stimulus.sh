#!/bin/bash
# The user button (PC13) of the emulated board: the GPIOC model reads the pin
# level from the FIFO /tmp/gpioc_pc13 ('0' pressed, '1' released). Presses it
# PRESSES times after a few seconds and prints the LED (PA5) levels the GPIOA
# model reports on /tmp/gpioa_out.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
trap 'kill 0' EXIT
(cat /tmp/gpioa_out 2>/dev/null &)
sleep "${DELAY:-4}"
for _ in $(seq "${PRESSES:-10}"); do
    printf 0 > /tmp/gpioc_pc13; sleep 0.25
    printf 1 > /tmp/gpioc_pc13; sleep 0.25
done
wait
