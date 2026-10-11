#!/bin/bash
# Serial input for the emulated USART2: a pseudo-terminal pair at /tmp/usart2_pty
# (the model's end) and /tmp/host_usart2 (ours). Prints what the firmware sends
# and, after a few seconds, types the 10 characters it waits for.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
TEXT="${TEXT:-BRunner123}"
rm -f /tmp/usart2_pty /tmp/host_usart2
socat PTY,link=/tmp/usart2_pty,raw,echo=0 PTY,link=/tmp/host_usart2,raw,echo=0 &
trap 'kill 0' EXIT
for _ in $(seq 50); do [ -e /tmp/host_usart2 ] && break; sleep 0.1; done
cat /tmp/host_usart2 &
sleep "${DELAY:-4}"
for c in $(echo "$TEXT" | fold -w1); do printf '%s' "$c" > /tmp/host_usart2; sleep 0.2; done
wait
