# I2C (two boards) (STM32F769I-EVAL, hybrid)

The master side of ST's I2C TwoBoards example (10-bit address `0x30F`): it transmits a message to the other board, then reads the other board's message.

Only part of the hardware is modeled: `i2c1_model.c` (I2C1) and `stm32f7_i2c_slave.c`, the second board as a slave on the I2C bus; no second board is needed.

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
boardrunner run -c i2c_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep "\[elder\] Read.*address = 0x40005424" fastdyn_work/io.log | grep -oE "value = 0x[0-9a-f]+" | head -4   # the slave's message: " ****I2C_TwoBoards ..."
```
