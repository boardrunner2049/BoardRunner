# NUCLEO-H753ZI: hybrid workloads

SDK workloads of the paper's Table 5 rehosted in a hybrid setup: the peripherals
the firmware is tested on have a model BoardRunner learned, and the rest of the
hardware stays on the real board, reached over the ST-LINK while the board runs
the idle firmware (`../idle_firmware/`).

| Workload | Models | Input |
|---|---|---|
| `ADC_with_DMA` | ADC1/ADC2 + DMA1/DMAMUX1 | none |
| `GPIO` | GPIOB | none |
| `GPIO_INT` | GPIOC + EXTI | emulated button presses (`stimulus.sh`) |
| `I2C` | I2C1, BME280 slave | the board's user button |
| `MQTT` | USART3 | an MQTT broker (`stimulus.sh`) |
| `PWM` | TIM3 | none |
| `SPI` | SPI1, BME280 slave | the board's user button |
| `TIMER` | TIM3 | none |
| `UART` | USART3 | the board's user button, then characters (`stimulus.sh`) |

Each workload folder has the firmware (`firmwares/`), the models
(`generated_models/`), the platform configuration and a README with the build,
run and expected results. The firmware reports its result on the board's LEDs.
Flash the idle firmware once, then build and run from a workload's folder:

```bash
../idle_firmware/flash.sh
cd TIMER
boardrunner build-models generated_models -o build
boardrunner run -c timer_config.toml
```
