# PWM (STM32F769I-EVAL, hybrid)

ST's TIM_PWMOutput example: TIM3 generates PWM signals on its four channels.

Only part of the hardware is modeled: `tim3_model.c`: TIM3.

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
boardrunner run -c pwm_config.toml    # Ctrl-C after about 8 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Write.*address = 0x40000400" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | tail -1   # TIM3_CR1 with CEN set: counter enabled
```
