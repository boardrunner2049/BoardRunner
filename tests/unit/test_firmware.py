"""Running firmware (firmware.py), recording traces (hitl/capture.py) and the
pipeline's run step, with fastdyn.run_config replaced by a stand-in run."""

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import fastdyn
from boardrunner.cli import cli
from boardrunner.errors import BoardRunnerError
from boardrunner.firmware import run_firmware
from boardrunner.hitl.capture import capture_trace
from boardrunner.viomapper.pipeline import RunRequest, firmware_run_step

# pytest's temporary folders are too long for the QMP socket FastDyn would put in them.
CONFIG_TEXT = '[Machine]\nplatform = "STM32F103xx"\nqmp_socket = "/tmp/boardrunner-test.sock"\n'


def _handler(model="elder", enabled=True):
    return SimpleNamespace(model=model, enabled=enabled, scroll="from/the/config.so")


class FakeRun:
    """Behaves like fastdyn.run_config: calls adjust, runs until shutdown()
    (or 5 s), writes io.log into the work directory."""

    def __init__(self, devices=None, write_trace=True, fail=None):
        self.devices = devices or {"usart2": SimpleNamespace(handlers=[_handler()])}
        self.write_trace, self.fail = write_trace, fail
        self.calls, self.duration = [], None

    def __call__(self, config, work_dir, *, svd=None, adjust=None):
        self.calls.append((config, work_dir, svd))
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        stopped = threading.Event()
        handle = SimpleNamespace(machines={"machine0": SimpleNamespace(devices=self.devices)},
                                 shutdown=stopped.set)
        start = time.monotonic()
        adjust(handle)
        if self.fail:
            time.sleep(0.3)  # QEMU fails a moment after starting
            raise self.fail
        stopped.wait(5)
        self.duration = time.monotonic() - start
        if self.write_trace:
            (Path(work_dir) / "io.log").write_text("[ 0.1] [passthrough] Read: address = 0x40004400\n")
        return [SimpleNamespace(exit_code=-9)]


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "board.toml"
    path.write_text(CONFIG_TEXT)
    return path


@pytest.fixture
def fake(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(fastdyn, "run_config", run)
    return run


def test_a_run_stops_after_its_time_and_returns_the_trace(config, fake, tmp_path):
    outcome = run_firmware(config, tmp_path / "run", seconds=0.2, scrolls={"usart2": "/models/usart2.so"})

    assert outcome.trace == tmp_path / "run" / "io.log" and outcome.trace.is_file()
    assert 0.15 < fake.duration < 2 and outcome.exit_codes == [-9]
    assert fake.devices["usart2"].handlers[0].scroll == "/models/usart2.so"


def test_the_stimulus_runs_during_the_run_and_is_stopped(config, fake, tmp_path):
    marker = tmp_path / "stimulus.pid"
    run_firmware(config, tmp_path / "run", seconds=0.5,
                 stimulus=f'echo $$ "$FASTDYN_WORK_DIR" > {marker}; sleep 60')

    pid, work = marker.read_text().split()
    assert work == str((tmp_path / "run").resolve())
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid), 0)


def test_a_failed_run_still_stops_the_stimulus(config, monkeypatch, tmp_path):
    monkeypatch.setattr(fastdyn, "run_config", FakeRun(fail=RuntimeError("QEMU exited with code 1")))
    marker = tmp_path / "stimulus.pid"

    with pytest.raises(BoardRunnerError, match="the run of .* failed: QEMU exited with code 1"):
        run_firmware(config, tmp_path / "run", seconds=5, stimulus=f"echo $$ > {marker}; sleep 60")
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


@pytest.mark.parametrize("devices, scrolls, message", [
    ({"usart2": SimpleNamespace(handlers=[_handler()])}, {"uart4": "x.so"},
     "the configuration has no device uart4; its devices: usart2"),
    ({"usart2": SimpleNamespace(handlers=[_handler("passthrough")])}, {"usart2": "x.so"},
     r"\[Device.usart2\] has no enabled elder handler"),
    ({"usart2": SimpleNamespace(handlers=[_handler(enabled=False)])}, {"usart2": "x.so"},
     r"\[Device.usart2\] has no enabled elder handler"),
])
def test_models_need_a_matching_elder_device(config, monkeypatch, tmp_path, devices, scrolls, message):
    monkeypatch.setattr(fastdyn, "run_config", FakeRun(devices=devices))

    with pytest.raises(BoardRunnerError, match=message):
        run_firmware(config, tmp_path / "run", seconds=0.1, scrolls=scrolls)


def test_a_run_without_device_models_has_no_trace(config, monkeypatch, tmp_path):
    monkeypatch.setattr(fastdyn, "run_config", FakeRun(write_trace=False))

    with pytest.raises(BoardRunnerError, match="wrote no io.log"):
        run_firmware(config, tmp_path / "run", seconds=0.1)


def test_a_work_dir_too_long_for_the_qmp_socket_is_refused(config, fake, tmp_path):
    config.write_text('[Machine]\nplatform = "STM32F103xx"\n')  # QMP socket in the work dir

    with pytest.raises(BoardRunnerError, match="too long for QEMU's control socket"):
        run_firmware(config, tmp_path / ("x" * 120), seconds=0.1)
    assert fake.calls == []

    config.write_text(CONFIG_TEXT)  # the socket is elsewhere
    run_firmware(config, tmp_path / ("x" * 120), seconds=0.1)


def test_capture_saves_the_trace(config, fake, tmp_path):
    out = capture_trace(config, tmp_path / "traces" / "uart.trace", seconds=0.1)

    assert out.read_text().startswith("[ 0.1] [passthrough]")
    assert fake.calls[0][1] == str(tmp_path / "traces" / "uart.trace.run")


def test_the_trace_command(config, fake, tmp_path):
    result = CliRunner().invoke(cli, ["trace", "-c", str(config), "-o", str(tmp_path / "hw.trace"),
                                      "--seconds", "0.1"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "hw.trace").is_file()


def test_the_run_step_loads_each_round_s_libraries(config, fake, tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    (build / "usart2_model.so").write_bytes(b"")
    step = firmware_run_step(config, seconds=0.1)

    trace = step(RunRequest(2, {"USART2": str(tmp_path / "usart2_model.c")}, str(build), str(tmp_path / "w")))

    assert trace == str(tmp_path / "w" / "runs" / "round_2" / "io.log")
    assert fake.devices["usart2"].handlers[0].scroll == str(build / "usart2_model.so")


def test_the_run_step_device_override_and_missing_library(config, fake, tmp_path):
    fake.devices["serial"] = fake.devices.pop("usart2")
    build = tmp_path / "build"
    build.mkdir()
    request = RunRequest(1, {"USART2": str(tmp_path / "u.c")}, str(build), str(tmp_path / "w"))

    with pytest.raises(BoardRunnerError, match="model library not built: .*u.so"):
        firmware_run_step(config, seconds=0.1, devices={"USART2": "serial"})(request)
    (build / "u.so").write_bytes(b"")
    firmware_run_step(config, seconds=0.1, devices={"USART2": "serial"})(request)
    assert fake.devices["serial"].handlers[0].scroll == str(build / "u.so")
