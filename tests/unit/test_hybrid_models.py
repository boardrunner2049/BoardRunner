"""The hybrid examples' models (examples/<board>/hybrid): the paper's learned
models on FastDyn's model ABI v2 and LibVIO v1, with the rest of the hardware
on the board."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
MODELS = sorted(EXAMPLES.glob("*/hybrid/*/generated_models/*.c"))


def _is_slave(model):
    return model.stem.endswith("_slave")


def test_every_hybrid_workload_has_models_a_config_and_a_readme():
    workloads = sorted({m.parents[1] for m in MODELS})
    assert workloads
    for workload in workloads:
        assert list(workload.glob("*.toml")), workload
        assert list(workload.glob("firmwares/*")), workload
        assert (workload / "README.md").is_file(), workload


@pytest.mark.parametrize("model", MODELS, ids=lambda p: f"{p.parts[-5]}/{p.parts[-3]}/{p.name}")
def test_no_old_interface_is_left(model):
    text = model.read_text()
    for old in ("ConfigSection", "<device.h>", "<boardrunner/vio.h>", "dev_debug", "STM32F4_",
                "api_i2c_init_bus", "api_spi_init_bus"):
        assert old not in text, old
    assert not re.search(r"^static \w+ \*?g_\w+(\s*=[^;]*)?;", text, re.M), "global state"
    if _is_slave(model):
        assert "const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;" in text
    else:
        assert "const FdModel fastdyn_model = {" in text and "calloc(1, sizeof" in text


def test_configs_name_only_files_of_their_workload():
    for workload in sorted({m.parents[1] for m in MODELS}):
        for config in workload.glob("*.toml"):
            text = config.read_text()
            assert "boardrunner_examples" not in text and "boardrunner_sdk" not in text, config
            for so in re.findall(r'scroll\s*=\s*"build/(\w+)\.so"', text):
                assert (workload / "generated_models" / f"{so}.c").is_file(), (config, so)


def _toolchain():
    root = os.environ.get("FASTDYN_REPO_ROOT")
    qemu = root and (Path(root) / "third_party" / "common" / "qemu" / "include").is_dir()
    vio = shutil.which("pkg-config") and subprocess.run(["pkg-config", "--exists", "vio"]).returncode == 0
    return qemu and vio and shutil.which("nm")


@pytest.mark.skipif(not _toolchain(), reason="needs FASTDYN_REPO_ROOT with the QEMU headers, LibVIO and nm")
def test_hybrid_models_build_and_export_only_their_interface(tmp_path):
    from fastdyn import build_models
    from fastdyn.model_build import Model

    models = [Model(f"{p.parts[-5]}_{p.parts[-3]}_{p.stem}", [p]) for p in MODELS]
    report = build_models(models, tmp_path, keep_going=True)
    assert report.ok, [r.diagnostics for r in report.results if r.status == "failed"]
    for result in report.results:
        symbols = subprocess.run(["nm", "-D", "--defined-only", result.output], capture_output=True,
                                 text=True, check=True).stdout
        exported = {line.split()[-1] for line in symbols.splitlines() if line.split()[1] in "TDRB"}
        if result.name.endswith("_slave"):
            assert "vio_slave_abi" in exported and exported <= {
                "vio_slave_abi", "vio_i2c_slave_init", "vio_i2c_slave_event", "vio_i2c_slave_send",
                "vio_i2c_slave_recv", "vio_spi_slave_init", "vio_spi_slave_set_cs", "vio_spi_slave_transfer"}
        else:
            assert exported == {"fastdyn_model"}, (result.name, exported)
