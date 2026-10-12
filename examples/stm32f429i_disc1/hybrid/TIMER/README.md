# Timer (STM32F429I-DISC1, hybrid)

TIM1 runs as a time base with a 1 s period; its update interrupt toggles LD3.

Only part of the hardware is modeled: `tim1_model.c`: TIM1.

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

No input is needed; LD3 on the board blinks.

```bash
boardrunner run -c tim_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x00000029" fastdyn_work/io.log   # TIM1 update: about one per second
grep -c "Write.*address = 0x40021814" fastdyn_work/io.log                # LD3 writes, one per interrupt
```
