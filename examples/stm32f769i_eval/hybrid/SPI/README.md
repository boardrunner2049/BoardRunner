# SPI (two boards) (STM32F769I-EVAL, hybrid)

The master side of ST's SPI FullDuplex example on SPI1: one full-duplex transfer of 97 bytes with the other board.

Only part of the hardware is modeled: `spi1_model.c` (SPI1) and `stm32f7_spi_slave.c`, the second board as a slave on the SPI bus; no second board is needed.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Power the board (its external 5 V supply), connect its ST-LINK USB port and
flash the idle firmware once:

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
boardrunner run -c spi_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "\[elder\] Read.*address = 0x4001300C" fastdyn_work/io.log   # bytes received from the slave
```
