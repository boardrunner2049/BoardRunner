# MQTT (NUCLEO-H753ZI, hybrid)

An MQTT 3.1.1 client (Eclipse Paho `MQTTPacket`) over USART3: it connects to the broker, subscribes to `stm32/cmd`, publishes a counter on `stm32/sensor` every 2 s, and turns LD2 on and off on the commands `on` and `off`.

Only part of the hardware is modeled: `usart3_model.c`: USART3, connected to the host through the pseudo-terminal `/tmp/usart1_pty`, which `stimulus.sh` connects to an MQTT broker.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Connect the board over USB and flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

The firmware reports its result on the board's LEDs: LD1 (green, PB0), LD2
(yellow, PE1) and LD3 (red, PB14). In the MMIO trace they are writes to the
GPIOB and GPIOE `BSRR` registers (`0x58020418`, `0x58021018`): value
`0x00000001` turns LD1 on, `0x00000002` LD2 and `0x00004000` LD3; values in the
upper half (`0x00010000`, ...) turn them off.

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

Needs a Mosquitto broker on `localhost:1883` (`sudo apt install mosquitto mosquitto-clients`; it starts as a service) and `socat`. `stimulus.sh` connects `/tmp/usart1_pty` to the broker, prints what the firmware publishes and, after 12 s, sends `on` and then `off` on `stm32/cmd`. Start it before the run: the pseudo-terminal must exist when the model opens it.

```bash
./stimulus.sh &
boardrunner run -c mqtt_config.toml    # Ctrl-C after about 25 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints stm32/sensor {"n":0}, {"n":1}, ... and "sent: on", "sent: off"
grep "Write.*address = 0x58021018" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+"   # ... 0x00000002 (on), 0x00020000 (off)
```
