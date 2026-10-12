# I2C (BME280) (MAX78000FTHR, hybrid)

I2C1 master in polling mode talking to a BME280 at `0x76`: it writes the soft-reset command, then reads the chip ID (`0x60`).

Only part of the hardware is modeled: `i2c1_model.c` (I2C1) and `bme280_i2c_slave.c`, the BME280 as a slave on the I2C bus; no sensor needs to be wired. The slave model is the NUCLEO-F103RB's BME280 model (the same sensor at the same address).

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
boardrunner run -c i2c_config.toml    # Ctrl-C after about 10 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# console: "Writing 0xB6 to reset register (0xE0)... OK", "Chip ID: 0x60 (expected 0x60)", "All tests PASSED"
grep "\[elder\] Read" fastdyn_work/io.log | grep -c "value = 0x0*60\b"   # 1: the chip ID was read
```
