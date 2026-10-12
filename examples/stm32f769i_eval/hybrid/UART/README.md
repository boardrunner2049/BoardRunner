# UART (STM32F769I-EVAL, hybrid)

ST's UART_HyperTerminal_IT example on USART1: it prints a banner, asks for 10 characters, sends them back and prints "Example Finished".

Only part of the hardware is modeled: `usart1_model.c`: USART1, connected to the host through the pseudo-terminal `/tmp/usart1_pty`.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Power the board (its external 5 V supply), connect its ST-LINK USB port and
flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

`stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_usart1`, prints what the firmware sends and types 10 characters. To type yourself instead: `socat PTY,link=/tmp/usart1_pty,raw,echo=0 STDIO`, started before the run.

```bash
./stimulus.sh &
boardrunner run -c uart_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints the banner, "Enter 10 characters using keyboard :", the 10 characters and "Example Finished"
```
