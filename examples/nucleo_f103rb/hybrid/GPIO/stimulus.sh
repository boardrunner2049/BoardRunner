#!/bin/bash
# The user button (PC13) of the emulated GPIO model: bytes on the FIFO
# /tmp/gpioc_in (0x00 pressed, 0x01 released). Presses it PRESSES times after a
# few seconds and prints the LED (PA5) changes the model reports on /tmp/gpioa_out.
# For the pseudo-terminal flavor (gpio_pty_model) see the README.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
trap 'kill 0' EXIT
for f in /tmp/gpioc_in /tmp/gpioa_out; do [ -p "$f" ] || { rm -f "$f"; mkfifo "$f"; }; done
cat /tmp/gpioa_out &
exec 3<>/tmp/gpioc_in
sleep "${DELAY:-4}"
for _ in $(seq "${PRESSES:-5}"); do
    printf '\x00' >&3; sleep 0.5
    printf '\x01' >&3; sleep 0.5
done
wait
