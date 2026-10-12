# GPIO (NUCLEO-H753ZI, hybrid)

Blinks an on-board LED by setting and clearing its pin; it starts on LD3 (PB14).

Only part of the hardware is modeled: `gpiob_model.c`: GPIOB, the port of LD1 and LD3.

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

No input is needed; LD3 blinks about every 0.25 s.

```bash
boardrunner run -c gpio_config.toml    # Ctrl-C after about 10 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "Write.*address = 0x58020418" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | head -6   # 0x00004000 / 0x40000000: LD3 on / off
```
