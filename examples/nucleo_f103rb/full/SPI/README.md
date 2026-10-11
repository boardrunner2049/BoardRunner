# SPI (BME280) (NUCLEO-F103RB)

SPI2 master, polling: writes the BME280 `config` register (`0xF5` ← `0x1C`), reads it back and turns LD2 on if the sensor returned `0x1C`. Chip select is PB12, driven as a GPIO. Covers the paper's SPI test.

Every peripheral the firmware uses has a learned model, so it runs without the
board: RCC, FLASH, GPIOA, SPI2 (SPI2 and GPIOB, since the chip select on PB12 is part of the transaction) and the BME280 sensor as a slave on the SPI bus.

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

No input is needed; the transaction completes within a second.

```bash
boardrunner run -c spi_config.toml    # Ctrl-C after about 5 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log`, are in `fastdyn_work/`.

## What to expect

```bash
grep "Read.*address = 0x4000380C" fastdyn_work/io.log | grep -oE "value = 0x[0-9A-Fa-f]+"   # ... 1C 1C
grep -c "0x40010810.*value = 0x00000020" fastdyn_work/io.log                          # 1: LED on
```

## Learn the models again

`hardware_log/io.trace` is the MMIO trace recorded on the board. BoardRunner learns the models from it,
runs the firmware with them and corrects them until the run matches the trace (the LLM needs
`OPENAI_API_KEY`, see the main README):

```bash
boardrunner pipeline -hw hardware_log/io.trace -c spi_config.toml -b STM32F103xx \
    -p SPI2 -p GPIOB -mname SPI2 -ms SPI2 -ms GPIOB -o learned/spi2_model.c \
    --build-dir build_learned --seconds 5 -d work
```

The learned models are written to `learned/`; `work/pipeline.json` records each round. The stages can
also be run one by one (`encode`, `codegen`, `run`, `verify`, `rca`; see the main README).

## The hardware trace

Wiring, BME280 breakout in SPI mode:

| BME280 | MCU pin | Nucleo header |
|---|---|---|
| VCC | 3V3 | CN6 pin 4 |
| GND | GND | CN6 pin 6 |
| SCK / SCL | PB13 (SPI2_SCK) | CN10 pin 30 |
| SDO | PB14 (SPI2_MISO) | CN10 pin 28 |
| SDI / SDA | PB15 (SPI2_MOSI) | CN10 pin 26 |
| CSB | PB12 (CS) | CN10 pin 16 |

Recording it again needs the board. In the configuration, enable every `passthrough` handler and
disable every `elder` handler (and enable the `remaining_space` passthrough), so every peripheral
access goes to the real MCU over the ST-Link; flash the idle firmware once, then record:

```bash
../../idle_firmware/flash.sh
boardrunner trace -c spi_config.toml -o hardware_log/recorded.trace --seconds 5
```
