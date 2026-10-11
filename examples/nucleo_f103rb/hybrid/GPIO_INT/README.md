# GPIO interrupt (NUCLEO-F103RB, hybrid)

Pressing the user button raises the EXTI15_10 interrupt; its callback reads PC13 and toggles LD2.

Only part of the hardware is modeled: `gpioc_model.c`: GPIOC. EXTI, AFIO and the NVIC run on the board, so the interrupt comes from the real button: press the blue button B1 during the run.

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

Press B1 a few times while it runs.

```bash
boardrunner run -c gpio_int_config.toml    # Ctrl-C after about 20 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Write.*0x40010414" fastdyn_work/io.log   # EXTI pending cleared: one per button edge
grep -c "Write.*0x40010810" fastdyn_work/io.log   # LD2 writes: two per press
```

The board signals the interrupt again after each one is served (the hardware-in-the-loop interrupt forwarding), so `Interrupt Taken ... 0x00000038` appears far more often than the presses; the firmware finds nothing pending and returns.
