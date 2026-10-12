# GPIO (STM32F769I-EVAL, hybrid)

Sets and clears GPIOI pins in a loop.

Only part of the hardware is modeled: `gpioi_model.c`: GPIOI.

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

No input is needed.

```bash
boardrunner run -c gpio_config.toml    # Ctrl-C after about 10 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "\[elder\] Write.*address = 0x400220" fastdyn_work/io.log   # GPIOI writes, handled by the model
```
