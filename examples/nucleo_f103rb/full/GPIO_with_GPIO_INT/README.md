# GPIO + GPIO interrupt (NUCLEO-F103RB)

PC13 (the user button) raises the EXTI15_10 interrupt; the handler reads PC13 and drives LD2 (PA5). Covers the paper's GPIO tests: read, set and clear a pin, and run a callback after a pin interrupt.

Every peripheral the firmware uses has a learned model, so it runs without the
board: RCC, FLASH, AFIO, EXTI, GPIOA and GPIOC; GPIOC and EXTI are linked by a signal line (pin level → edge → interrupt).

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

`stimulus.sh` presses the button 10 times through the FIFO `/tmp/gpioc_pc13` and prints the LED level the GPIOA model reports on `/tmp/gpioa_out` (`PA5=1` on press, `PA5=0` on release).

```bash
./stimulus.sh &
boardrunner run -c gpio.toml    # Ctrl-C after about 14 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log`, are in `fastdyn_work/`.

## What to expect

```bash
grep -c "Interrupt Taken.*Vector = 0x00000038" fastdyn_work/io.log   # 20: one EXTI interrupt per edge
```

## Learn the models again

`hardware_log/io.trace` is the MMIO trace recorded on the board. BoardRunner learns the models from it,
runs the firmware with them and corrects them until the run matches the trace (the LLM needs
`OPENAI_API_KEY`, see the main README):

```bash
boardrunner pipeline -hw hardware_log/io.trace -c gpio.toml -b STM32F103xx \
    -m GPIOA:learned/gpioa_model.c:GPIOA -m GPIOC:learned/gpioc_model.c:GPIOC,EXTI,AFIO -m EXTI:learned/exti_model.c:EXTI,GPIOC,AFIO,NVIC \
    --build-dir build_learned --seconds 14 --stimulus ./stimulus.sh -d work
```

The learned models are written to `learned/`; `work/pipeline.json` records each round. The stages can
also be run one by one (`encode`, `codegen`, `run`, `verify`, `rca`; see the main README).

## The hardware trace

Recording it again needs the board. In the configuration, enable every `passthrough` handler and
disable every `elder` handler (and enable the `remaining_space` passthrough), so every peripheral
access goes to the real MCU over the ST-Link; flash the idle firmware once, then record:

```bash
../../idle_firmware/flash.sh
boardrunner trace -c gpio.toml -o hardware_log/recorded.trace --seconds 20
```

Press the blue user button (B1) a few times while it records.
