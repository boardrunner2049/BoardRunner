# NUCLEO-F103RB: hybrid workloads

SDK workloads of the paper's Table 5 rehosted in a hybrid setup: the peripherals
the firmware is tested on have a model BoardRunner learned, and the rest of the
hardware stays on the real board, reached over the ST-LINK while the board runs
the idle firmware (`../idle_firmware/`).

| Workload | Models | Input |
|---|---|---|
| `ADC_with_DMA` | ADC1 + DMA1 | none |
| `GPIO` | GPIOA + GPIOC (FIFO or pseudo-terminal flavor) | button presses (`stimulus.sh`) |
| `GPIO_INT` | GPIOC | the board's user button |
| `I2C` | I2C1, BME280 slave | none |
| `PWM` | TIM3 | none |
| `SPI` | SPI2, BME280 slave | none |
| `TIMER` | TIM3 | none |
| `UART` | USART2 | characters (`stimulus.sh`) |

Each workload folder has the firmware (`firmwares/`), the models
(`generated_models/`), the platform configuration and a README with the build,
run and expected results. Flash the idle firmware once, then build and run from
a workload's folder:

```bash
../idle_firmware/flash.sh
cd UART
boardrunner build-models generated_models -o build
./stimulus.sh &
boardrunner run -c uart_config.toml
```
