# NUCLEO-F103RB examples

Peripheral models that BoardRunner learned for seven firmware workloads of
the STM32 NUCLEO-F103RB board, the fully rehosted workloads of the paper
(Tables 5-7). With them, the firmware runs on FastDyn without the board.

| Workload | Models |
|---|---|
| `GPIO_with_GPIO_INT` | rcc, flash, gpioa, gpioc, afio, exti |
| `UART` | rcc, flash, gpioa, usart2 |
| `SPI` | rcc, flash, gpioa, spi2, BME280 slave |
| `I2C` | rcc, flash, gpioa, gpiob, afio, i2c1, BME280 slave |
| `ADC_with_DMA` | rcc, flash, gpioa, adc1, dma1 |
| `TIMER` | rcc, flash, gpioa, tim3 |
| `PWM` | rcc, flash, gpioa, tim3 |

Each model is a C file using FastDyn's model interface
(`<fastdyn/device_model.h>`) and LibVIO; the BME280 slaves sit on the SPI and
I2C buses. Build a workload's models:

```bash
fastdyn build-model examples/nucleo_f103rb/UART/generated_models -o build/models/uart
```
