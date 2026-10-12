# Timer (NUCLEO-H753ZI, hybrid)

TIM3 runs as a time base with a 1 s period and its update interrupt. LD1 turns on when the callback has run, LD2 when the counter advanced between two reads, LD3 on failure.

Only part of the hardware is modeled: `tim3_model.c`: TIM3.

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

No input is needed.

```bash
boardrunner run -c timer_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x0000002D" fastdyn_work/io.log   # TIM3: about one per second
grep -c "Write.*address = 0x58020418.*value = 0x00000001" fastdyn_work/io.log   # 1: callback ran
grep -c "Write.*address = 0x58021018.*value = 0x00000002" fastdyn_work/io.log   # 1: counter advanced
```
