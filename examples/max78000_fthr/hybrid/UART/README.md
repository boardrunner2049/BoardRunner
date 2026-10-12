# UART (MAX78000FTHR, hybrid)

Prompts on UART0, receives 5 characters, echoes each one and checks that they spell `Hello`.

Only part of the hardware is modeled: `uart_model.c`: UART0, connected to the host through the pseudo-terminal `/tmp/usart1_pty`.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses through OpenOCD while the board runs the idle firmware. This
needs the OpenOCD of Analog Devices' MSDK (`MAXIM_PATH` is the MSDK folder).
Connect the board over its USB port (CN1) and flash the idle firmware once:

```bash
MAXIM_PATH=/path/to/MaximSDK ../../idle_firmware/flash.sh
```

During a run, keep the MSDK's OpenOCD server running in a second terminal;
FastDyn connects to it:

```bash
$MAXIM_PATH/Tools/OpenOCD/openocd -s $MAXIM_PATH/Tools/OpenOCD/scripts \
    -f interface/cmsis-dap.cfg -f target/max78000.cfg
```

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

`stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_usart1`, prints what the firmware sends and types `Hello`. To type yourself instead: `socat PTY,link=/tmp/usart1_pty,raw,echo=0 STDIO`, started before the run.

```bash
./stimulus.sh &
boardrunner run -c uart_config.toml    # Ctrl-C after about 15 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints the prompt, the echoed "Hello", "Received:    "Hello" (RX verified)" and "Data matches. Test PASSED"
```
