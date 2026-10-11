# UART (NUCLEO-F103RB)

Prints a banner on USART2 (the ST-Link virtual COM port), waits for 10 characters, then prints a success message and turns LD2 on. Covers the paper's UART test: receive and transmit a byte.

Every peripheral the firmware uses has a learned model, so it runs without the
board: RCC, FLASH, GPIOA and USART2; USART2 talks to the host through a pseudo-terminal.

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

`stimulus.sh` creates the pseudo-terminal pair `/tmp/usart2_pty` (the model's end) and `/tmp/host_usart2`, prints what the firmware sends and types `BRunner123`. To type yourself instead: `socat PTY,link=/tmp/usart2_pty,raw,echo=0 STDIO`, started before the run.

```bash
./stimulus.sh &
boardrunner run -c uart_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log`, are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints the banner, the echoed characters and "[ DONE ] Received 10 characters."
grep -c 0x40004404 fastdyn_work/io.log   # 237: 227 DR writes and 10 DR reads
```

## Learn the models again

`hardware_log/io.trace` is the MMIO trace recorded on the board. BoardRunner learns the models from it,
runs the firmware with them and corrects them until the run matches the trace (the LLM needs
`OPENAI_API_KEY`, see the main README):

```bash
boardrunner pipeline -hw hardware_log/io.trace -c uart_config.toml -b STM32F103xx \
    -p USART2 -o learned/usart2_model.c \
    --build-dir build_learned --seconds 15 --stimulus ./stimulus.sh -d work
```

The learned models are written to `learned/`; `work/pipeline.json` records each round. The stages can
also be run one by one (`encode`, `codegen`, `run`, `verify`, `rca`; see the main README).

## The hardware trace

Recording it again needs the board. In the configuration, enable every `passthrough` handler and
disable every `elder` handler (and enable the `remaining_space` passthrough), so every peripheral
access goes to the real MCU over the ST-Link; flash the idle firmware once, then record:

```bash
../../idle_firmware/flash.sh
boardrunner trace -c uart_config.toml -o hardware_log/recorded.trace --seconds 20
```

Type 10 characters on the board's virtual COM port while it records (`minicom -D /dev/ttyACM0 -b 115200`).
