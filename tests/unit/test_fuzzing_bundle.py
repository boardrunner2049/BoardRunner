"""evaluation/fuzzing (Table 8): the launchers' inputs exist and fit together."""

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[2] / "evaluation" / "fuzzing"
TEMPLATES = sorted(BUNDLE.glob("configs/*/*.toml.in"))
MODELS = sorted(BUNDLE.glob("models/*_fuzzing_model.c"))
PLACEHOLDERS = {"__FIRMWARE__", "__MAIN_RAM__", "__RAM1__", "__QMP_SOCKET__", "__QEMU_LOG__",
                "__MODEL_PATH__", "__CPU__", "__MONITOR_PORT__"}


def test_the_bundle_has_its_templates_models_and_launchers():
    assert {p.name for p in TEMPLATES} == {
        "lwip.toml.in", "modbus.toml.in", "mqtt.toml.in", "qemu_only.toml.in", "sdcard.toml.in"}
    assert [p.name for p in MODELS] == ["lwip_fuzzing_model.c", "modbus_fuzzing_model.c", "mqtt_fuzzing_model.c"]
    for script in ("common.sh", "run_qemu_coverage.sh", "run_board_coverage.sh", "run_aflnet_coverage.sh"):
        assert (BUNDLE / "scripts" / script).is_file(), script


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_templates_parse_once_filled_and_name_no_old_tree(template):
    text = template.read_text()
    assert set(re.findall(r"__[A-Z0-9_]+__", text)) <= PLACEHOLDERS
    for old in ("boardrunner_examples", "boardrunner_sdk", "build-aflnet", "/dev/shm", "plugin_library"):
        assert old not in text, old
    filled = re.sub(r"__MONITOR_PORT__", "5555", text)
    filled = re.sub(r"__[A-Z0-9_]+__", "x", filled)
    tomllib.loads(filled)


def test_the_launchers_firmware_and_models_exist():
    common = (BUNDLE / "scripts" / "common.sh").read_text()
    repo = BUNDLE.parents[1]
    paths = re.findall(r'\]="\$examples/([^"]+)"', common)
    assert len(paths) == 8
    for path in paths:
        assert (repo / "examples" / path).is_file(), path


def _toolchain():
    root = os.environ.get("FASTDYN_REPO_ROOT")
    qemu = root and (Path(root) / "third_party" / "common" / "qemu" / "include").is_dir()
    vio = shutil.which("pkg-config") and subprocess.run(["pkg-config", "--exists", "vio"]).returncode == 0
    return qemu and vio and shutil.which("nm")


@pytest.mark.skipif(not _toolchain(), reason="needs FASTDYN_REPO_ROOT with the QEMU headers, LibVIO and nm")
def test_the_fuzzing_models_build_and_export_only_their_interface(tmp_path):
    from fastdyn import build_models
    from fastdyn.model_build import Model

    report = build_models([Model(p.stem, [p]) for p in MODELS], tmp_path, keep_going=True)
    assert report.ok, [r.diagnostics for r in report.results if r.status == "failed"]
    for result in report.results:
        symbols = subprocess.run(["nm", "-D", "--defined-only", result.output], capture_output=True,
                                 text=True, check=True).stdout
        exported = {line.split()[-1] for line in symbols.splitlines() if line.split()[1] in "TDRB"}
        assert exported == {"fastdyn_model"}, (result.name, exported)
        undefined = subprocess.run(["nm", "-D", "--undefined-only", result.output], capture_output=True,
                                   text=True, check=True).stdout.split()
        assert not [u for u in undefined if u.startswith(("dev_", "core_register", "api_i2c_init"))], \
            (result.name, undefined)
