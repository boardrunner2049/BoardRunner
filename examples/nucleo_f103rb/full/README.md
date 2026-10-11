# NUCLEO-F103RB: fully rehosted workloads

Seven STM32CubeF1 SDK workloads for the STM32 NUCLEO-F103RB board, one per
peripheral class of the paper's Table 7. Every peripheral the firmware uses
has a model BoardRunner learned, so each one runs on FastDyn without the
board.

| Workload | Paper test (Table 7) | Models |
|---|---|---|
| `GPIO_with_GPIO_INT` | read, set and clear a pin; callback after a pin interrupt | rcc, flash, afio, gpioa, gpioc, exti |
| `UART` | receive and transmit a byte | rcc, flash, gpioa, usart2 |
| `SPI` | receive and transmit a byte (BME280) | rcc, flash, gpioa, spi2, BME280 slave |
| `I2C` | read and write a byte to a slave (BME280) | rcc, flash, afio, gpioa, gpiob, i2c1, BME280 slave |
| `ADC_with_DMA` | read a conversion; transfer a register to RAM | rcc, flash, gpioa, adc1, dma1 |
| `TIMER` | read the counter; callback after an interrupt | rcc, flash, gpioa, tim3 |
| `PWM` | configure PWM as an autonomous peripheral | rcc, flash, gpioa, tim3 |

Each workload folder holds everything needed to run it and to learn its
models again:

```
<workload>/
├── firmwares/*.elf          the firmware
├── generated_models/*.c     the learned models (and the BME280 slave models)
├── hardware_log/io.trace    the MMIO trace recorded on the board
├── *.toml                   the FastDyn platform configuration
├── stimulus.sh              drives the firmware's input (GPIO and UART only)
└── README.md                build, run, learn and record commands
```

The models are C files using FastDyn's model interface
(`<fastdyn/device_model.h>`) and LibVIO. The rcc, flash, gpioa and afio
models are the same file in every workload. Build and run one workload from
its folder:

```bash
cd UART
boardrunner build-models generated_models -o build
./stimulus.sh &
boardrunner run -c uart_config.toml
```

Recording a hardware trace again needs the board with the idle firmware of
`../idle_firmware/` flashed (`../idle_firmware/flash.sh`).

`../../../evaluation/nucleo_f103rb/run.sh example all` runs all seven and
checks each one's result; see `evaluation/nucleo_f103rb/README.md`.
