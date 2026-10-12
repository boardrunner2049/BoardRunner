# Modbus RTU (NUCLEO-F103RB, hybrid)

A FreeMODBUS RTU slave (address 10) on USART2 with coils, discrete inputs, input and holding registers, a clamped setpoint and a small command state machine (CALIBRATE / RESET).

Only part of the hardware is modeled: `usart2_model.c`: USART2, connected to the host through the pseudo-terminal `/tmp/usart1_pty`, on which `host/modbus_bridge.py` acts as the Modbus master.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Connect the board over USB and flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

Needs `socat`, `pymodbus` and `pyserial` (`pip install pymodbus pyserial`). `stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_modbus`, and after 5 s runs the bridge: 19 checks over function codes 01, 02, 03, 04, 05, 06, 0F and 10, the setpoint clamp, the state machine and an out-of-range exception (`REPEAT=3` runs them 3 times).

```bash
./stimulus.sh &
boardrunner run -c modbus_config.toml    # Ctrl-C after about 30 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints 19 "[OK ]" lines and "Total failures: 0"
```
