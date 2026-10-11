"""The NUCLEO-F103RB canary models (examples/nucleo_f103rb): the paper's learned
models ported to FastDyn's model ABI v2 and LibVIO v1."""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "nucleo_f103rb" / "full"
MODELS = sorted(EXAMPLES.glob("*/generated_models/*.c"))
SLAVES = {"bme280_i2c_slave.c", "bme280_slave.c"}
WORKLOADS = ["ADC_with_DMA", "GPIO_with_GPIO_INT", "I2C", "PWM", "SPI", "TIMER", "UART"]


def test_every_canary_workload_has_its_models():
    assert sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir()) == WORKLOADS
    assert len(MODELS) == 35  # 16 distinct models; rcc, flash, gpioa in all 7, afio in 2


@pytest.mark.parametrize("model", MODELS, ids=lambda p: f"{p.parts[-3]}/{p.name}")
def test_no_old_interface_is_left(model):
    text = model.read_text()
    for old in ("ConfigSection", "<device.h>", "<boardrunner/vio.h>", "dev_debug", "slave_i2c_", "slave_spi_",
                "api_i2c_init_bus", "api_spi_init_bus"):
        assert old not in text, old
    assert not re.search(r"^static \w+ g_\w+;", text, re.M), "global state"
    if model.name in SLAVES:
        assert "const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;" in text
    else:
        assert "const FdModel fastdyn_model = {" in text and "calloc(1, sizeof(*s))" in text


@pytest.mark.parametrize("name", ["rcc_model.c", "flash_model.c", "gpioa_model.c", "afio_model.c"])
def test_shared_models_are_identical_copies(name):
    copies = [p for p in MODELS if p.name == name]
    assert len(copies) >= 2
    assert len({hashlib.sha256(p.read_bytes()).hexdigest() for p in copies}) == 1


def _toolchain():
    root = os.environ.get("FASTDYN_REPO_ROOT")
    qemu = root and (Path(root) / "third_party" / "common" / "qemu" / "include").is_dir()
    vio = shutil.which("pkg-config") and subprocess.run(["pkg-config", "--exists", "vio"]).returncode == 0
    return qemu and vio and shutil.which("nm")


@pytest.mark.skipif(not _toolchain(), reason="needs FASTDYN_REPO_ROOT with the QEMU headers, LibVIO and nm")
def test_canary_models_build_and_export_only_their_interface(tmp_path):
    from fastdyn import build_models
    from fastdyn.model_build import Model

    models = [Model(f"{p.parts[-3]}_{p.stem}", [p]) for p in MODELS]
    report = build_models(models, tmp_path, keep_going=True)
    assert report.ok, [r.diagnostics for r in report.results if r.status == "failed"]
    for result in report.results:
        symbols = subprocess.run(["nm", "-D", "--defined-only", result.output], capture_output=True,
                                 text=True, check=True).stdout
        exported = {line.split()[-1] for line in symbols.splitlines() if line.split()[1] in "TDRB"}
        if result.name.endswith(("bme280_i2c_slave", "bme280_slave")):
            assert "vio_slave_abi" in exported and exported <= {
                "vio_slave_abi", "vio_i2c_slave_init", "vio_i2c_slave_event", "vio_i2c_slave_send",
                "vio_i2c_slave_recv", "vio_spi_slave_init", "vio_spi_slave_set_cs", "vio_spi_slave_transfer"}
        else:
            assert exported == {"fastdyn_model"}, (result.name, exported)
