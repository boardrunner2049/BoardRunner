# PWM (MAX78000FTHR, hybrid)

TMR2 generates a 1 kHz PWM signal at 50 % duty; after starting it the firmware idles.

Only part of the hardware is modeled: `tmr2_model.c`: TMR2.

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

No input is needed. The firmware prints on UART0, which runs on the board: watch the board's serial console (`picocom -b 115200 /dev/ttyACM0`, or the port the board shows up as).

```bash
boardrunner run -c pwm_config.toml    # Ctrl-C after about 10 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# console: "Period: 1843 ticks", "Duty:   921 ticks (50%)", "PASSED"
```
