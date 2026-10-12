# I2C (BME280) (NUCLEO-H753ZI, hybrid)

I2C1 master talking to a BME280 at address `0x76`: after the button press it writes the soft-reset command, then reads the chip ID (`0x60`). LD1 turns on after the reset, LD2 after a correct chip ID, LD3 on any failure.

Only part of the hardware is modeled: `i2c1_model.c` (I2C1) and `bme280_i2c_slave.c`, the BME280 as a slave on the I2C bus; no sensor needs to be wired.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Connect the board over USB and flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

The firmware reports its result on the board's LEDs: LD1 (green, PB0), LD2
(yellow, PE1) and LD3 (red, PB14). In the MMIO trace they are writes to the
GPIOB and GPIOE `BSRR` registers (`0x58020418`, `0x58021018`): value
`0x00000001` turns LD1 on, `0x00000002` LD2 and `0x00004000` LD3; values in the
upper half (`0x00010000`, ...) turn them off.

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

The firmware waits for the blue user button B1 (PC13), which is read from the real board: press it once a few seconds into the run.

```bash
boardrunner run -c i2c_config.toml    # Ctrl-C after about 20 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Read.*address = 0x40005424" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+"   # 0x00000060: chip ID
grep -c "Write.*address = 0x58020418.*value = 0x00000001" fastdyn_work/io.log   # 2: once at start, once after the reset
grep -c "Write.*address = 0x58021018.*value = 0x00000002" fastdyn_work/io.log   # 1: chip ID correct
grep -c "Write.*address = 0x58020418.*value = 0x00004000" fastdyn_work/io.log   # 0: no failure
```
