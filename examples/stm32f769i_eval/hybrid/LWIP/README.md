# lwIP HTTP server (STM32F769I-EVAL, hybrid)

ST's LwIP_HTTP_Server_Raw application: an lwIP web server at `192.168.8.2` with an LED control page (`/STM32F7xxLED.html`, `/leds.cgi`).

Only part of the hardware is modeled: `ethernet_model.c`: the Ethernet MAC, MMC and DMA, connected to the host through a TAP interface named by `ETH_TAP`.

The peripherals that have no model run on the real board: FastDyn forwards
their accesses over the ST-LINK while the board runs the idle firmware.
Power the board (its external 5 V supply), connect its ST-LINK USB port and
flash the idle firmware once:

```bash
../../idle_firmware/flash.sh
```

All commands run from this folder.

## Build the models

```bash
boardrunner build-models generated_models -o build
```

## Run

Create the TAP interface once (needs root), then run with `ETH_TAP=tap0`:

```bash
sudo ip tuntap add dev tap0 mode tap user $(whoami)
sudo ip addr add 192.168.8.1/24 dev tap0
sudo ip link set dev tap0 up
export ETH_TAP=tap0
```

Once it runs, open `http://192.168.8.2/` (e.g. `curl http://192.168.8.2/`).

```bash
boardrunner run -c lwip_config.toml    # Ctrl-C after about 60 s
```

The run's files, including its MMIO trace `fastdyn_work/io.log` (`[elder]` lines are the
models, `[passthrough]` lines the board), are in `fastdyn_work/`.

## What to expect

```bash
curl -s http://192.168.8.2/ | grep -o "<title>[^<]*"   # the server's home page, while it runs
```
