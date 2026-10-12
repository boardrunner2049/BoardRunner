# UART (STM32F429I-DISC1, hybrid)

Prints a greeting on USART1 and then echoes every character it receives.

Only part of the hardware is modeled: `usart1_model.c`: USART1, connected to the host through the pseudo-terminal `/tmp/usart1_pty`.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Connect the board over USB and flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

The firmware reports its result on the board's LEDs LD3 (green, PG13) and LD4
(red, PG14). In the MMIO trace they are writes to GPIOG: `ODR` (`0x40021814`,
bit `0x2000` LD3, `0x4000` LD4) or `BSRR` (`0x40021818`: `0x00002000` turns LD3
on, `0x20000000` off; `0x00004000` / `0x40000000` the same for LD4).

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

`stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_usart1`, prints what the firmware sends and types `hello` after 6 s. To type yourself instead: `socat PTY,link=/tmp/usart1_pty,raw,echo=0 STDIO`, started before the run.

```bash
./stimulus.sh &
boardrunner run -c usart_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints "Hello UART at 115200 baud!", then the echoed "hello"
```
