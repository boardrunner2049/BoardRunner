# I2C (two boards) (STM32F429I-DISC1, hybrid)

The master side of ST's I2C TwoBoards example (10-bit address `0x30F`): after a button press it transmits a message to the other board, after a second press it reads it back and compares. LD3 is on between the transmit and the receive; LD4 turns on on any error.

Only part of the hardware is modeled: `i2c1_model.c` (I2C1) and `stm32f4_i2c_slave.c`, the second board as a slave on the I2C bus that echoes what it received; no second board is needed.

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

The firmware waits twice for the blue user button B1 (PA0), which is read from the real board (the black button is reset). Press it once a few seconds into the run, and again a few seconds later.

```bash
boardrunner run -c i2c_config.toml    # Ctrl-C after about 25 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Read.*address = 0x40005410" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | head -4   # 0x20 0x2a 0x2a ...: " ****I2C_TwoBoards ..." read back
grep "Write.*address = 0x40021818" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | tail -2   # 0x00002000, 0x20000000: LD3 on, off
grep -c "Write.*address = 0x40021818.*value = 0x00004000" fastdyn_work/io.log   # 0: LD4 (error) never on
```
