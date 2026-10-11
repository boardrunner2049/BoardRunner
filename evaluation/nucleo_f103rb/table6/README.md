# Table 6: BoardRunner and naive peripheral handling

Unique basic blocks each SDK firmware executes when its peripherals are
handled by each mode, whether it passes its functional check (FC), and
whether the peripheral output matches the hardware trace (TV). Run with
`../run.sh table6 ...`; see `../README.md`.

| Mode | Board? | Peripheral accesses are |
|---|---|---|
| passthrough | yes | forwarded to the chip (the reference) |
| null | no | answered with 0 on read; writes are dropped |
| replay | no | served from `tapes/<fw>/record.trace`, recorded on the board |
| boardrunner | no | handled by the learned models (`examples/nucleo_f103rb/full/<workload>/generated_models`) |

## How the count is taken

`coverage = true` in the platform configuration makes FastDyn record the
address of every basic block the firmware executes; `bbl.txt` in the run's
work directory lists each address once. The count is its number of lines.

## Results

Paper:

| Firmware | Passthrough | Null | Replay | BoardRunner |
|---|---|---|---|---|
| GPIO (cbk) | 191 | 101 | 191 | 191 |
| UART | 415 | 352 | 415 | 415 |
| I2C | 438 | 304 | 438 | 438 |
| SPI | 291 | 262 | 291 | 291 |
| ADC+DMA | 378 | 265 | 378 | 378 |
| **FC** | ✓ | ✗ | ✗ | ✓ |
| **TV** | ✓ | ✗ | ✓ | ✓ |

The firmware binaries here (built with different compiler flags than the
measured ones):

| Firmware | Passthrough | Null | Replay | BoardRunner |
|---|---|---|---|---|
| GPIO (cbk) | 218 | 102 | 218 | 218 |
| UART | 415 | 352 | 415 | 415 |
| I2C | 438 | 304 | 438 | 438 |
| SPI | 291 | 262 | 291 | 291 |
| ADC+DMA | 370 | 268 | 370 | 370 |
| **FC** | ✓ | ✗ | ✗ | ✓ |
| **TV** | ✓ | ✗ | ✓ | ✓ |

Passthrough, Replay and BoardRunner execute the same set of blocks, Null a
strict subset; `results/<fw>/<mode>.txt` are the block lists behind the
numbers. The GPIO passthrough count depends on the button being pressed
during the run, since the interrupt and callback blocks run only on a press.

Null fails every functional check. Replay fails GPIO and UART, the two
firmwares driven by input, because it repeats the recording instead of
answering this run's presses and characters; it passes I2C, SPI and
ADC+DMA. TV is `../run.sh verify <fw>`.

## Files

```
configs/<fw>/{null,replay,passthrough,record}.toml   platform configurations (boardrunner: the workload's own)
tapes/<fw>/record.trace                              the recordings replay serves
results/<fw>/<mode>.txt                              the block lists of the table above
```

`<fw>` is one of `gpio uart i2c spi adc`. `../run.sh table6 <fw> record`
(board) records a new tape into the results folder; copy it over
`tapes/<fw>/record.trace` to replay it.
