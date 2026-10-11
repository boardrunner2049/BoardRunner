# ADC + DMA (NUCLEO-F103RB)

ADC1 converts continuously; DMA1 channel 1 moves every result from `ADC1->DR` into a RAM buffer and raises its transfer interrupt, which the firmware services in a loop. Covers the paper's ADC test.

Every peripheral the firmware uses has a learned model, so it runs without the
board: RCC, FLASH, GPIOA, ADC1 and DMA1 (ADC1 requests the DMA transfer, DMA1 writes RAM and raises the interrupt).

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

The run's files, including its MMIO trace `fastdyn_work/io.log`, are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x0000001B" fastdyn_work/io.log   # DMA1 channel 1, more than 1000 in 10 s
```

## Learn the models again

`hardware_log/io.trace` is the MMIO trace recorded on the board. BoardRunner learns the models from it,
runs the firmware with them and corrects them until the run matches the trace (the LLM needs
`OPENAI_API_KEY`, see the main README):

```bash
boardrunner pipeline -hw hardware_log/io.trace -c adc_with_dma_config.toml -b STM32F103xx \
    -m DMA1:learned/dma1_model.c:DMA1,ADC1,NVIC -m ADC1:learned/adc1_model.c:ADC1,DMA1 \
    --build-dir build_learned --seconds 10 -d work
```

The learned models are written to `learned/`; `work/pipeline.json` records each round. The stages can
also be run one by one (`encode`, `codegen`, `run`, `verify`, `rca`; see the main README).

## The hardware trace

Recording it again needs the board. In the configuration, enable every `passthrough` handler and
disable every `elder` handler (and enable the `remaining_space` passthrough), so every peripheral
access goes to the real MCU over the ST-Link; flash the idle firmware once, then record:

```bash
../../idle_firmware/flash.sh
boardrunner trace -c adc_with_dma_config.toml -o hardware_log/recorded.trace --seconds 10
```
