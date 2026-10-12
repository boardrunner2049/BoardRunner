# MAX78000FTHR: hybrid workloads

SDK workloads of the paper's Table 5 rehosted in a hybrid setup: the peripherals
the firmware is tested on have a model BoardRunner learned, and the rest of the
hardware stays on the real board, reached through the MSDK's OpenOCD while the
board runs the idle firmware (`../idle_firmware/`).

| Workload | Models | Input |
|---|---|---|
| `ADC` | ADC | none |
| `CNN_mnist` | UART0 (the CNN accelerator runs on the board) | none (`stimulus.sh` shows the output) |
| `DMA_M2M` | DMA | none |
| `GPIO` | GPIO2 | none |
| `GPIO_INT` | GPIO0 | emulated button presses (`stimulus.sh`) |
| `I2C` | I2C1, BME280 slave | none |
| `PWM` | TMR2 | none |
| `SPI` | SPI0, loopback slave | none |
| `TIMER` | TMR1 | none |
| `UART` | UART0 | characters (`stimulus.sh`) |

Each workload folder has the firmware (`firmwares/`), the models
(`generated_models/`), the platform configuration and a README with the build,
run and expected results. Flash the idle firmware once, start the MSDK's OpenOCD server
in a second terminal (`../idle_firmware/README.md`), then build and run from a
workload's folder:

```bash
MAXIM_PATH=/path/to/MaximSDK ../idle_firmware/flash.sh
cd TIMER
boardrunner build-models generated_models -o build
boardrunner run -c timer_config.toml
```
