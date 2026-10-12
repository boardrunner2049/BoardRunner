# GPIO interrupt (MAX78000FTHR, hybrid)

SW1 (P0.2) is a falling-edge interrupt input; the interrupt handler toggles the red LED (P2.0) and prints a line.

Only part of the hardware is modeled: `gpio0_model.c`: GPIO0, with SW1 driven from the FIFO `/tmp/max78000_gpio0_pin2` (`0` low, `1` high, `t` toggle), so the button is emulated.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses through OpenOCD while the board runs the idle firmware. This
needs the OpenOCD of Analog Devices' MSDK (`MAXIM_PATH` is the MSDK folder).
Connect the board over its USB port (CN1) and flash the idle firmware once:

```bash
MAXIM_PATH=/path/to/MaximSDK ../../idle_firmware/flash.sh
```

During a run, keep the MSDK's OpenOCD server running in a second terminal;
FastDyn connects to it:

```bash
$MAXIM_PATH/Tools/OpenOCD/openocd -s $MAXIM_PATH/Tools/OpenOCD/scripts \
    -f interface/cmsis-dap.cfg -f target/max78000.cfg
```

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

`stimulus.sh` presses the emulated SW1 5 times through the FIFO. The firmware prints on UART0, which runs on the board: watch the board's serial console (`picocom -b 115200 /dev/ttyACM0`, or the port the board shows up as).

```bash
./stimulus.sh &
boardrunner run -c gpio_int_config.toml    # Ctrl-C after about 20 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# console: "Interrupt callback executed! LED1 toggled." once per press
grep -c "Interrupt Taken.*Vector = 0x00000028" fastdyn_work/io.log   # GPIO0: 5, one per press
```
