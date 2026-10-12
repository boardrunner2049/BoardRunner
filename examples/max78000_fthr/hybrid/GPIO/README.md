# GPIO (MAX78000FTHR, hybrid)

Toggles the red LED (P2.0) every 500 ms.

Only part of the hardware is modeled: `gpio2_model.c`: GPIO2, the LED port.

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

No input is needed. The firmware prints on UART0, which runs on the board: watch the board's serial console (`picocom -b 115200 /dev/ttyACM0`, or the port the board shows up as). The firmware's 500 ms delay polls SysTick on the board through the probe, so the LED changes only every 2-3 s.

```bash
boardrunner run -c gpio_config.toml    # Ctrl-C after about 30 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# console: "Pin set (LED ON)" / "Pin cleared (LED OFF)" alternating; the model handles the GPIO2 writes:
grep -c "\[elder\] Write" fastdyn_work/io.log
```
