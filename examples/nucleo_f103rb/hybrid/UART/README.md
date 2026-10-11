# UART (NUCLEO-F103RB, hybrid)

Prints a banner on USART2, waits for 10 characters, then prints a success message and turns LD2 on.

Only part of the hardware is modeled: `usart2_model.c`: USART2, connected to the host through the pseudo-terminal `/tmp/usart1_pty`.

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

`stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_usart1`, prints what the firmware sends and types `BRunner123`. To type yourself instead: `socat PTY,link=/tmp/usart1_pty,raw,echo=0 STDIO`, started before the run.

```bash
./stimulus.sh &
boardrunner run -c uart_config.toml    # Ctrl-C after about 14 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints the banner, the typed characters and "[ DONE ] Received 10 characters."
```
