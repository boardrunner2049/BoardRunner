# I2C (BME280) (NUCLEO-F103RB, hybrid)

I2C1 master reading a BME280 sensor: chip ID, calibration data, then the measurement block in a loop, toggling LD2 each time.

Only part of the hardware is modeled: `i2c1_model.c` (I2C1) and `bme280_i2c_slave.c`, the BME280 as a slave on the I2C bus; no sensor needs to be wired.

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
boardrunner run -c i2c_config.toml    # Ctrl-C after about 8 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Read.*0x40005410" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | sed -n 2p   # chip ID 0x60
grep -c "Write.*0x40010810" fastdyn_work/io.log   # LD2 writes, one per measurement cycle
```
