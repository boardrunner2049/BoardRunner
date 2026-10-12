#!/bin/bash
# Connects the emulated USART3 (pseudo-terminal /tmp/usart1_pty) to the MQTT
# broker on localhost:1883, prints what the firmware publishes on stm32/sensor
# and, after DELAY seconds, sends "on" and then "off" on stm32/cmd (LED2).
# Needs mosquitto (running) and mosquitto-clients.
# Usable on its own (next to `boardrunner run`) or as `--stimulus ./stimulus.sh`.
BROKER="${BROKER:-localhost}"
rm -f /tmp/usart1_pty
socat PTY,link=/tmp/usart1_pty,raw,echo=0 "TCP:$BROKER:1883" &
trap 'kill 0' EXIT
mosquitto_sub -h "$BROKER" -t stm32/sensor -v &
sleep "${DELAY:-12}"
mosquitto_pub -h "$BROKER" -t stm32/cmd -m on;  echo "sent: on"
sleep 5
mosquitto_pub -h "$BROKER" -t stm32/cmd -m off; echo "sent: off"
wait
