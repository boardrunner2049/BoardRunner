# GPIO interrupt (NUCLEO-H753ZI, hybrid)

The user button (PC13) raises the EXTI15_10 interrupt; each press changes the blink rate of the LEDs.

Only part of the hardware is modeled: `gpioc_model.c` (GPIOC, with PC13 driven from the FIFO `/tmp/gpioc_pc13`) and `exti_model.c` (EXTI, raising EXTI15_10 on the rising edge of PC13). The button is emulated, so the board's B1 is not used.

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

`stimulus.sh` presses the emulated button 3 times, about 2 s apart, through `/tmp/gpioc_pc13`.

```bash
./stimulus.sh &
boardrunner run -c gpio_int_config.toml    # Ctrl-C after about 16 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "Interrupt Taken.*Vector = 0x00000038" fastdyn_work/io.log   # EXTI15_10: two per press (see below)
grep -E "Write.*address = 0x5802(0418|1018)" fastdyn_work/io.log | awk -F"[][]" '{print int($2)}' | uniq -c   # LED writes per second: the rate changes after each press
```

Each press shows the interrupt taken twice in a row: the second time the handler finds the EXTI pending bit already cleared and returns.
