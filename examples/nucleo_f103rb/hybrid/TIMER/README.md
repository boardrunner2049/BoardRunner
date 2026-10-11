# Timer (NUCLEO-F103RB, hybrid)

TIM3 runs as a time base with its update interrupt; the callback toggles LD2 about once a second.

Only part of the hardware is modeled: `tim3_model.c`: TIM3.

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

No input is needed; LD2 on the board blinks.

```bash
boardrunner run -c timer_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x0000002D" fastdyn_work/io.log   # TIM3 update: about one per second
grep -c "Write.*0x40010810" fastdyn_work/io.log                     # LD2 writes, one per interrupt
```
