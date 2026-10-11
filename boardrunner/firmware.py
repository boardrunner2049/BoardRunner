"""Run firmware on FastDyn for a fixed time and collect its MMIO trace.

Used for both kinds of run BoardRunner makes: recording the hardware trace
through a passthrough configuration (``boardrunner trace``) and running the
firmware with the learned models (the pipeline's run step). The run goes
through ``fastdyn.run_config``, exactly like ``fastdyn run``; FastDyn writes
the trace to ``<work>/io.log``.
"""

import logging
import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from boardrunner.errors import BoardRunnerError

log = logging.getLogger(__name__)

TRACE_FILE = "io.log"
DEFAULT_SECONDS = 10.0


@dataclass
class RunOutcome:
    trace: Path
    work_dir: Path
    exit_codes: List[int] = field(default_factory=list)


def _set_model_paths(handle, scrolls):
    """Point each named device's elder handler at a model library."""
    remaining = dict(scrolls)
    for machine in handle.machines.values():
        for name, device in machine.devices.items():
            if name not in remaining:
                continue
            elder = [h for h in device.handlers if h.model == "elder" and h.enabled]
            if not elder:
                raise BoardRunnerError(f"[Device.{name}] has no enabled elder handler to load the model into")
            for handler in elder:
                handler.scroll = str(remaining[name])
            log.info("Device %s uses %s", name, remaining[name])
            del remaining[name]
    if remaining:
        known = sorted({n for m in handle.machines.values() for n in m.devices})
        raise BoardRunnerError(f"the configuration has no device {', '.join(sorted(remaining))}; "
                               f"its devices: {', '.join(known)}")


def _start_stimulus(command, work_dir):
    log.info("Stimulus: %s", command)
    return subprocess.Popen(command, shell=True, start_new_session=True,
                            env={**os.environ, "FASTDYN_WORK_DIR": str(Path(work_dir).resolve())})


def _stop_stimulus(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def run_firmware(config, work_dir, *, seconds=DEFAULT_SECONDS, stimulus: Optional[str] = None,
                 scrolls: Optional[Dict[str, str]] = None, svd: Optional[str] = None):
    """Run ``config`` for ``seconds`` and return its trace.

    ``work_dir`` is replaced (as by ``fastdyn run``). ``scrolls`` maps device
    names to the model libraries their elder handler loads, overriding the
    configuration. ``stimulus`` is a shell command started just before QEMU
    starts and stopped when the run ends; it drives the firmware's inputs
    (e.g. types into a pseudo-terminal) and can read ``$FASTDYN_WORK_DIR``.
    """
    import fastdyn

    if seconds <= 0:
        raise BoardRunnerError(f"the run time must be positive, not {seconds}")
    work_dir = Path(work_dir)
    state = {}

    def adjust(handle):
        if scrolls:
            _set_model_paths(handle, scrolls)
        if stimulus:
            state["stimulus"] = _start_stimulus(stimulus, work_dir)
        timer = threading.Timer(seconds, handle.shutdown)
        timer.daemon = True
        timer.start()
        state["timer"] = timer

    log.info("Running %s for %g s in %s", config, seconds, work_dir)
    try:
        results = fastdyn.run_config(str(config), str(work_dir), svd=svd, adjust=adjust)
    except BoardRunnerError:
        raise
    except Exception as e:
        raise BoardRunnerError(f"the run of {config} failed: {e}") from e
    finally:
        if "timer" in state:
            state["timer"].cancel()
        _stop_stimulus(state.get("stimulus"))

    trace = work_dir / TRACE_FILE
    if not trace.is_file():
        raise BoardRunnerError(f"the run wrote no {TRACE_FILE} in {work_dir}: are device models (dev=) "
                               "enabled in the configuration?")
    return RunOutcome(trace, work_dir, [r.exit_code for r in results])
