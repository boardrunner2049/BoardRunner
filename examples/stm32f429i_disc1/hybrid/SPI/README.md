# SPI (two boards) (STM32F429I-DISC1, hybrid)

The master side of ST's SPI TwoBoards example on SPI4: after a button press it exchanges a message with the other board in one full-duplex transfer and compares what it received. LD3 turns on if the message matches, LD4 on any error.

Only part of the hardware is modeled: `spi4_model.c` (SPI4) and `stm32f4_spi_slave.c`, the second board as a slave on the SPI bus that answers with its message; no second board is needed.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Connect the board over USB and flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

The firmware reports its result on the board's LEDs LD3 (green, PG13) and LD4
(red, PG14). In the MMIO trace they are writes to GPIOG: `ODR` (`0x40021814`,
bit `0x2000` LD3, `0x4000` LD4) or `BSRR` (`0x40021818`: `0x00002000` turns LD3
on, `0x20000000` off; `0x00004000` / `0x40000000` the same for LD4).

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

The firmware waits for the blue user button B1 (PA0), which is read from the real board (the black button is reset). Press it once a few seconds into the run (LD3 blinks while it waits).

```bash
boardrunner run -c spi_config.toml    # Ctrl-C after about 20 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "Write.*address = 0x40021818" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | tail -1   # 0x00002000: LD3 on, message received
grep -c "Write.*address = 0x40021818.*value = 0x00004000" fastdyn_work/io.log   # 0: LD4 (error) never on
```
