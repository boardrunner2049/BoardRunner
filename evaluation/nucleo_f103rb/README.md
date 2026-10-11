# NUCLEO-F103RB evaluation

The seven fully rehosted SDK workloads (paper Table 7) and the comparison
with naive peripheral handling (Table 6), measured on the NUCLEO-F103RB
workloads in `examples/nucleo_f103rb/full/`. `run.sh` runs everything; no
board is needed except for the Passthrough column and for recording.

## Run with Docker

The image holds the patched QEMU, FastDyn, libhw, LibVIO and BoardRunner,
and runs `run.sh`. Build it from the repository root (the commands to check
out its sources are at the top of the `Dockerfile`):

```bash
docker build --build-context libvio=/path/to/LibVIO -t boardrunner .
mkdir -p results && cd results
docker run --rm -v "$PWD:/results" boardrunner example all    # the 7 workloads (Table 7), about 2 min
docker run --rm -v "$PWD:/results" boardrunner table6 all     # Table 6, Null / Replay / BoardRunner, about 5 min
docker run --rm -v "$PWD:/results" boardrunner verify uart    # trace verification of a BoardRunner run
```

## Run without Docker

With BoardRunner set up as in the main README (FastDyn built, LibVIO found
by `pkg-config vio`) and `socat` installed:

```bash
evaluation/nucleo_f103rb/run.sh example all
evaluation/nucleo_f103rb/run.sh table6 all
evaluation/nucleo_f103rb/run.sh verify uart
```

Results go to `/tmp/boardrunner-results` (`OUT=...` changes it; in Docker,
the mounted `/results`).

## Commands

| Command | What it does |
|---|---|
| `example <name> [secs]` | runs one workload (`GPIO_with_GPIO_INT UART SPI I2C ADC_with_DMA TIMER PWM`, or `all`) with its learned models, drives its input, and prints the unique basic blocks and the workload's functional check |
| `table6 <fw> <mode> [secs]` | one cell of Table 6: `fw` in `gpio uart i2c spi adc`, `mode` in `null replay boardrunner` |
| `table6 all [secs]` | the 15 cells that need no board, then the table (`table6.md`) |
| `verify <fw>` | trace verification (TV): BoardRunner's Verifier compares the I/O log of the `boardrunner` cell with the hardware trace |
| `check`, `flash` | board: check the ST-Link connection; flash the idle firmware |
| `table6 <fw> passthrough\|record [secs]` | board: the Passthrough column; record a new replay tape |

Each run is a fresh QEMU process stopped after `secs` seconds (default 10).
The I/O log of each run is kept: `examples/<name>.log` and
`table6/<fw>_<mode>.log`, with the block list in `table6/<fw>_<mode>.txt`.

The functional checks are the paper's Table 7 operations:

| Workload | Input | Functional check |
|---|---|---|
| GPIO | 10 presses of the emulated user button (PC13) | the interrupt callback ran once per edge |
| UART | 10 characters typed into the emulated USART2 | the firmware echoed them |
| SPI | none | the BME280 `config` register read back as written; LED on |
| I2C | none | the BME280 chip ID (`0x60`) was read |
| ADC+DMA | none | DMA transfer-complete interrupts fired |
| TIMER | none | TIM3 update interrupts fired |
| PWM | none | `TIM3->CNT` advances |

## Expected results

`example all`: every workload passes its functional check.

`table6 all`:

| Firmware | Null | Replay | BoardRunner |
|---|---|---|---|
| GPIO (cbk) | 102 | 218 | 218 |
| UART | 352 | 415 | 415 |
| I2C | 304 | 438 | 438 |
| SPI | 262 | 291 | 291 |
| ADC+DMA | 268 | 370 | 370 |
| **FC** | ✗ | ✗ | ✓ |

Replay and BoardRunner execute the same set of blocks (compare the `.txt`
files), and Null a strict subset of it. Null fails every functional check,
because no peripheral answers. Replay fails GPIO and UART: it repeats the
recording instead of answering this run's button presses and characters.
BoardRunner passes all of them. `verify <fw>` reports that the emulation
matches the hardware; warnings are expected (see below).

The firmware binaries were built from the SDK examples with different
compiler flags than the ones measured in the paper, so some counts differ
from the paper's Table 6 (GPIO 218 instead of 191, ADC+DMA 370 instead of
378, Null within ±3); the others are the same, and the relations between
the columns are the paper's. `table6/README.md` has both tables.

If a cell is far off or a functional check fails unexpectedly, run it
again with a longer window (`table6 <fw> <mode> 20`): the scripted inputs
are sent 3 s after QEMU starts, and on a busy host the firmware may not be
polling yet.

## With the board (optional)

With a NUCLEO-F103RB on USB you can also measure the Passthrough column and
record new replay tapes. SPI and I2C also need a Bosch BME280 breakout wired
to the board (wiring in `examples/nucleo_f103rb/full/SPI/README.md` and
`.../I2C/README.md`). Your user needs access to the ST-Link (USB
`0483:374b`, a udev rule or the `plugdev` group).

The board runs an idle firmware while FastDyn runs the real firmware in QEMU
and forwards every peripheral access to the chip
(`examples/nucleo_f103rb/idle_firmware/`). Flash it once:

```bash
docker run --rm -v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule='c 189:* rmw' \
    boardrunner check                                 # "Cortex-M3 r1p1 processor detected"
docker run --rm -v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule='c 189:* rmw' \
    boardrunner flash                                 # the idle firmware
docker run --rm -v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule='c 189:* rmw' \
    --device=/dev/ttyACM0 -v "$PWD:/results" boardrunner table6 uart passthrough
```

(Without Docker: `run.sh check`, `run.sh flash` or
`examples/nucleo_f103rb/idle_firmware/flash.sh`, `run.sh table6 uart
passthrough`.) `--device=/dev/ttyACM0` is needed only for `uart`, whose
characters are typed into the board's virtual COM port. For `gpio`, press the
blue user button during the run. `table6 <fw> record` also writes a new tape,
`table6/<fw>_record.trace`, which replaces `table6/tapes/<fw>/record.trace`.

## Notes

- Hardware traces recorded through the probe show the interrupt service
  routine entered a second time after each event, with the flag already
  cleared. The models raise one interrupt per event; the Verifier reports the
  difference as a warning, not a mismatch.
- The models can be learned again from the hardware traces with
  `boardrunner pipeline` (each workload's README). LLM output is not
  deterministic, so the number of correction rounds may differ; the
  Verifier's match is what counts.
