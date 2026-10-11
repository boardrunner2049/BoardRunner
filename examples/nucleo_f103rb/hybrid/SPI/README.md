# SPI (BME280) (NUCLEO-F103RB, hybrid)

SPI2 master: writes the BME280 `config` register, reads it back and turns LD2 on if the value matches.

Only part of the hardware is modeled: `spi_model.c` (SPI2 and the GPIOB chip select on PB12) and `bme280_slave.c`, the BME280 as a slave on the SPI bus; no sensor needs to be wired.

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
boardrunner run -c spi_config.toml    # Ctrl-C after about 8 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Read.*0x4000380C" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+"   # ... 0x1c 0x1c
grep "Write.*0x40010810" fastdyn_work/io.log | tail -1   # value 0x00000020: LD2 on
```
