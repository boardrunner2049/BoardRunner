# CNN (MNIST) (MAX78000FTHR, hybrid)

Loads weights into the on-chip CNN accelerator, classifies a 28x28 MNIST digit and prints the result. The accelerator runs on the board (passthrough); only UART0 is modeled.

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

`stimulus.sh` creates the pseudo-terminal pair `/tmp/usart1_pty` (the model's end) and `/tmp/host_usart1` and prints what the firmware sends. Loading the network's weights into the accelerator takes about 18,000 writes through the probe, so the result comes after about 2 minutes.

```bash
./stimulus.sh &
boardrunner run -c cnn_mnist_config.toml    # Ctrl-C after about 150 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
# stimulus.sh prints "*** CNN Inference Test ***", "*** PASS ***" and the classification: "Class 7: 100.0%"
```
