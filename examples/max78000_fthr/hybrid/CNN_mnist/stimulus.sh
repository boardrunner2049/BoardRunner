#!/bin/bash
# Output of the emulated UART0: a pseudo-terminal pair at /tmp/usart1_pty (the
# model's end) and /tmp/host_usart1 (ours); prints what the firmware sends.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
rm -f /tmp/usart1_pty /tmp/host_usart1
socat PTY,link=/tmp/usart1_pty,raw,echo=0 PTY,link=/tmp/host_usart1,raw,echo=0 &
trap 'kill 0' EXIT
for _ in $(seq 50); do [ -e /tmp/host_usart1 ] && break; sleep 0.1; done
cat /tmp/host_usart1
