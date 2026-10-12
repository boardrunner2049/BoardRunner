# GPIO interrupt (STM32F769I-EVAL, hybrid)

ST's GPIO_EXTI example: the Tamper/Key button (PC13) raises EXTI15_10, and its callback toggles an LED.

Only part of the hardware is modeled: `gpioc_model.c`: GPIOC, the button's port. EXTI and the NVIC run on the board, so the interrupt comes from the real button: press the Tamper/Key button a few times during the run.

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

Press the Tamper/Key button a few times while it runs.

```bash
boardrunner run -c gpio_int_config.toml    # Ctrl-C after about 20 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x00000038" fastdyn_work/io.log   # EXTI15_10: at least one per press
```
