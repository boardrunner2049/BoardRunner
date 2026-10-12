#!/bin/bash
# Serial input for the emulated USART3: a pseudo-terminal pair at /tmp/usart1_pty
# (the model's end) and /tmp/host_usart1 (ours). Prints what the firmware sends
# and, after DELAY seconds, types TEXT, which the firmware echoes back.
# The firmware only starts after the board's user button B1 is pressed: press it
# before DELAY (default 15 s) runs out.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
TEXT="${TEXT:-hello}"
rm -f /tmp/usart1_pty /tmp/host_usart1
socat PTY,link=/tmp/usart1_pty,raw,echo=0 PTY,link=/tmp/host_usart1,raw,echo=0 &
trap 'kill 0' EXIT
for _ in $(seq 50); do [ -e /tmp/host_usart1 ] && break; sleep 0.1; done
cat /tmp/host_usart1 &
sleep "${DELAY:-15}"
for c in $(echo "$TEXT" | fold -w1); do printf '%s' "$c" > /tmp/host_usart1; sleep 0.4; done
wait
