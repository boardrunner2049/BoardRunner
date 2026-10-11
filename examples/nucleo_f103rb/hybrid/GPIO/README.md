# GPIO (NUCLEO-F103RB, hybrid)

Reads the user button (PC13) and drives LD2 (PA5) from it (firmware from P2IM's test set).

Only part of the hardware is modeled: GPIOA and GPIOC in one model, in two flavors with the same register behavior: `gpio_fifo_model.c` (the configuration's default) takes the button from the FIFO `/tmp/gpioc_in` and reports LED changes on `/tmp/gpioa_out`; `gpio_pty_model.c` uses the pseudo-terminal `/tmp/usart1_pty` instead (type `b` to toggle the button). To use it, set the device's `scroll` to `build/gpio_pty_model.so`.

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

`stimulus.sh` presses the button 5 times through `/tmp/gpioc_in` and prints the LED changes.

```bash
./stimulus.sh &
boardrunner run -c gpio_config.toml    # Ctrl-C after about 14 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints one line per LED change, e.g. "gpioA ODR=0x0020 changed=0x0020": two per press
```
