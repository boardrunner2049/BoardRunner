# STM32F429I-DISC1: hybrid workloads

SDK workloads of the paper's Table 5 rehosted in a hybrid setup: the peripherals
the firmware is tested on have a model BoardRunner learned, and the rest of the
hardware stays on the real board, reached over the ST-LINK while the board runs
the idle firmware (`../idle_firmware/`).

| Workload | Models | Input |
|---|---|---|
| `ADC_with_DMA` | ADC3 + DMA2 | none |
| `GPIO` | GPIOG | none |
| `GPIO_INT` | GPIOG | the board's user button |
| `I2C` | I2C1, second-board slave | the board's user button (twice) |
| `PWM` | TIM3 | none |
| `SPI` | SPI4, second-board slave | the board's user button |
| `TIMER` | TIM1 | none |
| `UART` | USART1 | characters (`stimulus.sh`) |

Each workload folder has the firmware (`firmwares/`), the models
(`generated_models/`), the platform configuration and a README with the build,
run and expected results. Flash the idle firmware once, then build and run from
a workload's folder:

```bash
../idle_firmware/flash.sh
cd TIMER
boardrunner build-models generated_models -o build
boardrunner run -c tim_config.toml
```
