# GPIO interrupt (STM32F429I-DISC1, hybrid)

The user button B1 (PA0) raises EXTI0 on its rising edge; the interrupt handler toggles LD3, while the main loop blinks LD4. The firmware was written for BoardRunner (`../../idle_firmware/simple_tests/gpio_int_test.c`, built as described in `../../idle_firmware/README.md`).

Only part of the hardware is modeled: `gpiog_model.c`: GPIOG, the LEDs. The button, SYSCFG, EXTI and the NVIC run on the board, so the interrupt comes from the real button: press the blue button B1 a few times during the run.

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

Press B1 a few times while it runs.

```bash
boardrunner run -c gpio_int.toml    # Ctrl-C after about 20 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x00000016" fastdyn_work/io.log   # EXTI0: at least one per press (see below)
grep "\[elder\] Write.*address = 0x40021814" fastdyn_work/io.log | grep -c "value = 0x0000[67]000"   # writes with LD3 on
```

The board may signal the interrupt again after it is served (the hardware-in-the-loop interrupt forwarding), so `Interrupt Taken ... 0x00000016` can appear more often than the presses; the handler finds nothing pending and returns.
