# PWM (NUCLEO-F103RB, hybrid)

TIM3 channel 1 generates a PWM signal; the main loop samples `TIM3->CNT`.

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

No input is needed.

```bash
boardrunner run -c pwm_config.toml    # Ctrl-C after about 8 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Read.*0x40000424" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | head -5   # TIM3->CNT, increasing
```
