# PWM (NUCLEO-F103RB)

TIM3 channel 1 generates a PWM signal on PA6 (D12); the main loop samples `TIM3->CNT` every 10 ms. Covers the paper's PWM test.

Every peripheral the firmware uses has a learned model, so it runs without the
board: RCC, FLASH, GPIOA and TIM3.

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

No input is needed.

```bash
boardrunner run -c pwm_config.toml    # Ctrl-C after about 8 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log`, are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Read.*address = 0x40000424" fastdyn_work/io.log   # TIM3->CNT samples, more than 500
grep "Read.*address = 0x40000424" fastdyn_work/io.log | grep -oE "value = 0x[0-9A-Fa-f]+" | head -5   # increasing
```

## Learn the models again

`hardware_log/io.trace` is the MMIO trace recorded on the board. BoardRunner learns the models from it,
runs the firmware with them and corrects them until the run matches the trace (the LLM needs
`OPENAI_API_KEY`, see the main README):

```bash
boardrunner pipeline -hw hardware_log/io.trace -c pwm_config.toml -b STM32F103xx \
    -p TIM3 -p GPIOA -mname TIM3 -ms TIM3 -o learned/tim3_model.c \
    --build-dir build_learned --seconds 8 -d work
```

The learned models are written to `learned/`; `work/pipeline.json` records each round. The stages can
also be run one by one (`encode`, `codegen`, `run`, `verify`, `rca`; see the main README).

## The hardware trace

Recording it again needs the board. In the configuration, enable every `passthrough` handler and
disable every `elder` handler (and enable the `remaining_space` passthrough), so every peripheral
access goes to the real MCU over the ST-Link; flash the idle firmware once, then record:

```bash
../../idle_firmware/flash.sh
boardrunner trace -c pwm_config.toml -o hardware_log/recorded.trace --seconds 8
```

The PWM waveform is on PA6 (D12) of the board.
