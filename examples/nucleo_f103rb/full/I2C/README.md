# I2C (BME280) (NUCLEO-F103RB)

I2C1 master (100 kHz, remapped to PB8/PB9) talking to a BME280 at `0x76`: reads the chip ID and the calibration blocks, configures the sensor, then loops reading the 8-byte measurement block and toggling LD2 each time. Covers the paper's I2C test.

Every peripheral the firmware uses has a learned model, so it runs without the
board: RCC, FLASH, AFIO, GPIOA, GPIOB (bus recovery on PB8/PB9 before the pins go to the I2C peripheral), I2C1 and the BME280 sensor as a slave on the I2C bus.

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

No input is needed.

```bash
boardrunner run -c i2c_config.toml    # Ctrl-C after about 10 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log`, are in `fastdyn_work/`.

## What to expect

```bash
grep "Read.*address = 0x40005410" fastdyn_work/io.log | grep -oE "value = 0x[0-9A-Fa-f]+" | sed -n 2p   # chip ID 0x60
grep -c 0x40010810 fastdyn_work/io.log   # LED writes, one per measurement cycle
```

## Learn the models again

`hardware_log/io.trace` is the MMIO trace recorded on the board. BoardRunner learns the models from it,
runs the firmware with them and corrects them until the run matches the trace (the LLM needs
`OPENAI_API_KEY`, see the main README):

```bash
boardrunner pipeline -hw hardware_log/io.trace -c i2c_config.toml -b STM32F103xx \
    -m I2C1:learned/i2c1_model.c:I2C1,GPIOB,AFIO -m GPIOB:learned/gpiob_model.c:GPIOB \
    --build-dir build_learned --seconds 10 -d work
```

The learned models are written to `learned/`; `work/pipeline.json` records each round. The stages can
also be run one by one (`encode`, `codegen`, `run`, `verify`, `rca`; see the main README).

## The hardware trace

Wiring, Adafruit BME280 breakout in I2C mode:

| BME280 | NUCLEO-F103RB | Note |
|---|---|---|
| VIN | 3V3 (CN6 pin 4) | |
| GND | GND (CN6 pin 6) | |
| SCK / SCL | D15 = PB8 (CN5, top pin) | |
| SDI / SDA | D14 = PB9 (CN5, second pin) | |
| SDO | GND | address 0x76 |
| CS | unconnected | high = I2C mode |

Recording it again needs the board. In the configuration, enable every `passthrough` handler and
disable every `elder` handler (and enable the `remaining_space` passthrough), so every peripheral
access goes to the real MCU over the ST-Link; flash the idle firmware once, then record:

```bash
../../idle_firmware/flash.sh
boardrunner trace -c i2c_config.toml -o hardware_log/recorded.trace --seconds 10
```
