# UART (NUCLEO-H753ZI, hybrid)

After the button press, prints a banner on USART3 and echoes every character it receives, using the USART3 interrupt.

Only part of the hardware is modeled: `usart3_model.c`: USART3, connected to the host through the pseudo-terminal `/tmp/usart1_pty`. The button interrupt comes from the real board (EXTI and NVIC run there).

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

The firmware waits for the blue user button B1 (PC13), which is read from the real board: press it once a few seconds into the run. `stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_usart1`, prints what the firmware sends and types `hello` after 15 s. To type yourself instead: `socat PTY,link=/tmp/usart1_pty,raw,echo=0 STDIO`, started before the run.

```bash
./stimulus.sh &
boardrunner run -c uart_config.toml    # Ctrl-C after about 25 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints "**** UART Terminal Echo Ready ****", then the echoed "hello"
grep -c "Interrupt Taken.*Vector = 0x00000037" fastdyn_work/io.log   # USART3: one or more per character
```

The board signals the button interrupt again after each one is served (the hardware-in-the-loop interrupt forwarding), so `Interrupt Taken ... 0x00000038` appears far more often than the press; the firmware finds nothing pending and returns.
