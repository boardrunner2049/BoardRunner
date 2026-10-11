# ADC + DMA (NUCLEO-F103RB, hybrid)

ADC1 converts continuously and DMA1 channel 1 moves each result into a RAM buffer, raising its transfer interrupt.

Only part of the hardware is modeled: `adc_with_dma_model.c`: ADC1 and DMA1 in one model.

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
boardrunner run -c adc_with_dma_config.toml    # Ctrl-C after about 10 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x0000001B" fastdyn_work/io.log   # DMA1 channel 1: thousands in 10 s
```
