"""LibVIO's model contract and BoardRunner's rules as prompt text
(codegen/prompts/contract.py)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from boardrunner.viomapper.codegen.prompts import contract as contract_module
from boardrunner.viomapper.codegen.prompts.contract import ContractError, load_contract
from boardrunner.viomapper.codegen.prompts.prompt_gen import slave_model_gen


@pytest.fixture
def contract_copy(tmp_path, test_contract):
    copy = tmp_path / "contract"
    shutil.copytree(test_contract, copy)
    return copy


def test_the_directory_comes_from_the_argument_then_the_environment(contract_copy, test_contract):
    assert load_contract(contract_copy).directory == contract_copy.resolve()
    assert load_contract().directory == test_contract.resolve()  # $VIO_CONTRACT_DIR


def test_without_a_directory_pkg_config_is_asked(monkeypatch, contract_copy):
    monkeypatch.delenv(contract_module.CONTRACT_DIR_ENV)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{contract_copy}\n", stderr="")

    monkeypatch.setattr(contract_module.shutil, "which", lambda name: "/usr/bin/pkg-config")
    monkeypatch.setattr(contract_module.subprocess, "run", fake_run)

    assert load_contract().directory == contract_copy.resolve()
    assert calls == [["pkg-config", "--variable=contractdir", "vio"]]


def test_a_missing_contract_says_how_to_provide_one(monkeypatch):
    monkeypatch.delenv(contract_module.CONTRACT_DIR_ENV)
    monkeypatch.setattr(contract_module.shutil, "which", lambda name: "/usr/bin/pkg-config")
    monkeypatch.setattr(contract_module.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=""))

    with pytest.raises(ContractError, match="set VIO_CONTRACT_DIR, or put an installed LibVIO"):
        load_contract()


@pytest.mark.parametrize("version", ["1.1.0", "3.0.0", "one"])
def test_unsupported_versions_are_refused(contract_copy, version):
    (contract_copy / "VERSION").write_text(version + "\n")

    with pytest.raises(ContractError, match="need 1.2 or later, up to 2.x|not a version"):
        load_contract(contract_copy)


def test_a_section_without_an_audience_is_refused(contract_copy):
    reference = contract_copy / "api_summary.md"
    reference.write_text(reference.read_text().replace("<!-- for: model -->\n", "", 1))

    with pytest.raises(ContractError, match="has no audience"):
        load_contract(contract_copy)


def test_rules_keep_or_drop_the_libvio_only_text():
    contract = load_contract()

    with_vio, without_vio = contract.rules(vio=True), contract.rules(vio=False)

    assert "vio_spi_bus_init" in with_vio and "Observability and host I/O" in with_vio
    assert "vio_spi_bus_init" not in without_vio and "Observability and host I/O" not in without_vio
    assert "Stateful emulation over trace memorization" in without_vio
    for text in (with_vio, without_vio):
        assert "<!--" not in text
        assert text.startswith("## Rules for device models")  # one level below the prompt's title


def test_api_sections_are_picked_by_audience():
    contract = load_contract()

    model = contract.api(("model",))
    slave = contract.api(("model", "slave"))
    no_vio = contract.api(vio=False)

    assert "qemu_plugin_raise_irq" in model and "vio_i2c_bus_init" in model
    assert "vio_i2c_slave_send" not in model
    assert "vio_i2c_slave_send" in slave
    assert "vio_set_logger" not in model + slave  # for the host, not for models
    assert "qemu_plugin_raise_irq" in no_vio and "api_pty_fd_gen" not in no_vio
    assert "LibVIO" not in no_vio  # the host functions' LibVIO-only text goes too
    assert "<!--" not in model + slave + no_vio
    assert model.startswith("### Host functions for device models")
    assert "    I2C_START_RECV," in model  # code blocks are kept as they are


def test_slave_prompts_use_the_libvio_slave_interface(tmp_path):
    firmware = tmp_path / "sensor.c"
    firmware.write_text("int main(void) { return 0; }\n")
    reference = tmp_path / "reference.c"
    reference.write_text("/* reference slave */\n")

    path = slave_model_gen("BMP280", "STM32F103xx", str(tmp_path / "out"), str(firmware), str(reference))
    prompt = Path(path).read_text()

    assert "vio_i2c_slave_send" in prompt and "vio_slave_abi = VIO_SLAVE_ABI_VERSION" in prompt
    assert "api_pty_fd_gen" in prompt  # slaves may use the rest of LibVIO
    assert "vio_set_logger" not in prompt
    assert "fastdyn_model" not in prompt  # device-model rules are not for slaves
    assert "slave_i2c_event" not in prompt.replace("vio_i2c_slave_event", "")
    assert "g_state" not in prompt


def _installed_contract_dir():
    if os.environ.get("BOARDRUNNER_REAL_CONTRACT"):
        return Path(os.environ["BOARDRUNNER_REAL_CONTRACT"])
    if shutil.which("pkg-config"):
        result = subprocess.run(["pkg-config", "--variable=contractdir", "vio"],
                                capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    return None


REAL_RULES = Path(contract_module.__file__).resolve().parent / "model_rules.md"


def test_the_rules_are_boardrunners_own(contract_copy, test_contract):
    (contract_copy / "model_rules.md").write_text("# A 1.x contract's rules, not used\n")

    contract = load_contract(contract_copy)

    assert contract.rules() == load_contract(test_contract).rules()
    assert "not used" not in contract.rules()


def test_the_real_libvio_contract_loads(monkeypatch):
    directory = _installed_contract_dir()
    if directory is None or not directory.is_dir():
        pytest.skip("no LibVIO contract (set BOARDRUNNER_REAL_CONTRACT or install LibVIO)")
    monkeypatch.setattr(contract_module, "RULES_FILE", REAL_RULES)

    contract = load_contract(directory)

    model = contract.api(("model",))
    assert "int api_pty_fd_gen(const char *dev_name);" in model and "qemu_plugin_raise_irq" in model
    assert "vio_set_logger" not in model and "vio_i2c_slave_init" not in model
    assert "vio_i2c_slave_init" in contract.api(("model", "slave"))
    assert "fastdyn_model" in contract.rules()
    assert "api_signal_register" in contract.rules(vio=True)
    assert "api_signal_register" not in contract.rules(vio=False)
    assert "LibVIO" not in contract.api(vio=False) + contract.rules(vio=False)
