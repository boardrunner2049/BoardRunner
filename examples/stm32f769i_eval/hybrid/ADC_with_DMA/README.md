# ADC + DMA (STM32F769I-EVAL, hybrid)

ST's ADC_RegularConversion_DMA example: ADC3 converts continuously and DMA2 stream 0 moves each result into RAM; the conversion-complete callback runs from the DMA interrupt.

Only part of the hardware is modeled: `adc_with_dma_model.c`: ADC3 and DMA2 in one model.

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
boardrunner run -c adc_with_dma.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x00000048" fastdyn_work/io.log   # DMA2 stream 0 interrupts
```
