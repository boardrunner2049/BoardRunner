# Real-world firmware and fuzzing (Table 8)

The paper's Table 8: code coverage of four real-world firmware (Modbus on the
NUCLEO-F103RB, MQTT on the NUCLEO-H753ZI, lwIP and an SD-card FatFs
application on the STM32F769I-EVAL) under AFLNet fuzzing with BoardRunner's
models, against Elder (model-only) and QEMU-only baselines. Coverage is the
number of unique basic blocks the firmware executed (`bbl.txt`, one block per
line).

There are two ways to run the campaigns:

- **The published image** (`EVALUATION.md`): `pseclab/fastdyn-fuzzer:1.0.0`,
  the paper's version of the tools, built from the CCS '26 artifact snapshot
  (FastDyn `main` at `9c2e0b0`, archived at
  https://doi.org/10.6084/m9.figshare.33941068). Its launchers are the
  snapshot's `virtuals/fuzzer/run_*.sh`.
- **This repository** (below): the same campaigns on the current FastDyn,
  LibVIO and BoardRunner, from `scripts/`, natively or in an image built from
  this folder's `Dockerfile`.

## Run from this repository

| Launcher | Runs |
|---|---|
| `scripts/run_qemu_coverage.sh [all\|mqtt\|lwip\|sdcard\|modbus]` | the QEMU-only baseline: the firmware with no peripheral model (5 s each) |
| `scripts/run_board_coverage.sh {mqtt\|lwip\|sdcard\|modbus}` | the Elder baseline: the firmware with the learned model of the targeted peripheral; MQTT, lwIP and SD-card with the rest of the hardware on their board, Modbus without a board |
| `scripts/run_aflnet_coverage.sh {lwip\|mqtt\|modbus}` | an AFLNet campaign through the peripheral's fuzzing model (Modbus 100 s, MQTT 25 s, lwIP six phases, 6.5 min) |

Each takes a new work directory (`--work-dir PATH`, or the second argument of
`run_aflnet_coverage.sh`) and prints the basic-block count; `--help` lists the
options. The firmware are the BoardRunner examples' (`examples/*/hybrid/`), and
the Elder baselines use those examples' learned models.

### Native

FastDyn records coverage only when it is built with a fuzzing backend, so
build the pinned FastDyn (`deps/fastdyn`, with its patched QEMU and libhw
built as FastDyn's README describes) with AFLNet:

```bash
git clone https://github.com/CSmith1539/aflnet.git /path/to/aflnet
git -C /path/to/aflnet checkout 509a10384d53ce6dd6f04c6870454619dbf7d35e
make -C /path/to/aflnet afl-fuzz libaflnet.a      # needs libgraphviz-dev and libcap-dev
cd deps/fastdyn
meson setup build -Dqemu_path="$PWD/third_party/common/qemu" \
    -Dlibhw_path="$PWD/third_party/common/libhw" -Daflnet_path=/path/to/aflnet \
    -Ddevice_models=true -Denable_libhw=true -Denable_aflnet=true
ninja -C build
```

(or point `FASTDYN_REPO_ROOT` at a FastDyn checkout built that way).

Then, with `boardrunner` installed and LibVIO found by `pkg-config vio`:

```bash
evaluation/fuzzing/scripts/run_qemu_coverage.sh all --work-dir results/qemu
evaluation/fuzzing/scripts/run_board_coverage.sh modbus --work-dir results/modbus-elder
evaluation/fuzzing/scripts/run_aflnet_coverage.sh modbus results/modbus-aflnet
evaluation/fuzzing/scripts/run_aflnet_coverage.sh mqtt results/mqtt-aflnet
evaluation/fuzzing/scripts/run_aflnet_coverage.sh lwip results/lwip-aflnet
```

The Modbus baseline needs `socat` and the Python packages `pymodbus` and
`pyserial` (`host/modbus_bridge.py` of the Modbus example is its Modbus
master). The board baselines also need the board with its idle firmware
(`examples/<board>/idle_firmware/`): MQTT a running MQTT broker or `mosquitto`
(and `mosquitto-clients`, `socat`), lwIP the host interface `tap0` at
192.168.8.1/24 (`sudo ip tuntap add dev tap0 mode tap user $(whoami)`,
`sudo ip addr add 192.168.8.1/24 dev tap0`, `sudo ip link set dev tap0 up`),
SD-card `mkfs.fat` (dosfstools).

### Docker

```bash
docker build -f evaluation/fuzzing/Dockerfile --build-context libvio=/path/to/LibVIO -t boardrunner-fuzzing .
mkdir -p results
docker run --rm -v "$PWD/results:/results" boardrunner-fuzzing \
    evaluation/fuzzing/scripts/run_qemu_coverage.sh all --work-dir /results/qemu
docker run --rm -v "$PWD/results:/results" boardrunner-fuzzing \
    evaluation/fuzzing/scripts/run_aflnet_coverage.sh lwip /results/lwip-aflnet
```

The `Dockerfile` header lists the submodules to check out first. For a board
baseline, add the board's USB device as in `EVALUATION.md`
(`-v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule='c 189:* rmw'`, and
`--network=host --cap-add=NET_ADMIN --device=/dev/net/tun` for lwIP).

### Expected results

| Run | Basic blocks (published image; paper) |
|---|---|
| QEMU-only MQTT / lwIP / SD-card / Modbus | 196 / 124 / 103 / 123 (paper 29 / 170 / 141 / 157) |
| Elder Modbus | 521 (518) |
| AFLNet Modbus / MQTT | ≈611 / ≈902 (623 / 892) |
| AFLNet lwIP | ≈2,587, at least 2,501 (2,651) |
| Elder MQTT / lwIP / SD-card (board) | 869 / 1,814 / 1,393 (866 / 1,838 / 1,416) |

This repository gives the same QEMU-only and Elder Modbus counts; the AFLNet
counts vary by a few blocks with timing, and the lwIP campaign fails if it
stays at or below 2,500.

## Contents

```
models/          the fuzzing models: <target>_fuzzing_model.c for lwip, modbus, mqtt
                 (the baselines use the examples' models)
configs/aflnet/  the campaigns' FastDyn configurations, mqtt_snapshot_ranges.txt
configs/board/   the baselines' configurations (qemu_only, mqtt, lwip, sdcard, modbus)
seeds/           the saved AFLNet corpora (lwIP: one per campaign phase)
scripts/         the launchers and common.sh
Dockerfile       the image of the campaigns from this repository
EVALUATION.md    the runbook of the published image
```

The configurations are templates: the launchers fill in the firmware, the
model, and the run's RAM files and QMP socket (`__FIRMWARE__`, `__MODEL_PATH__`,
...). The fuzzing models keep their state in static variables, because
FastDyn's fuzzer callbacks (`<fastdyn/fuzz_hooks.h>`) take no context; one
model file serves one instance of each device it models (the MQTT one:
`usart3`, `clocktree`, `systick`).
