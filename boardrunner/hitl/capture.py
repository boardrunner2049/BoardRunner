"""Hardware in the loop: record the firmware's MMIO trace on the real board.

The configuration routes the peripherals to the board (FastDyn's passthrough
handler, through the ST-Link): the firmware runs in QEMU, and every
peripheral access is forwarded to the board and logged. The trace is the
ground truth the models are learned from (``boardrunner encode``) and
checked against (``boardrunner verify``).
"""

import logging
import shutil
from pathlib import Path

from boardrunner.firmware import DEFAULT_SECONDS, run_firmware

log = logging.getLogger(__name__)


def capture_trace(config, output, *, seconds=DEFAULT_SECONDS, stimulus=None, work_dir=None, svd=None):
    """Run the passthrough ``config`` for ``seconds`` and save its trace as ``output``.

    The run's own files stay in ``work_dir`` (default ``<output>.run/``).
    """
    output = Path(output)
    work_dir = Path(work_dir) if work_dir else output.with_name(output.name + ".run")
    outcome = run_firmware(config, work_dir, seconds=seconds, stimulus=stimulus, svd=svd)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(outcome.trace, output)
    lines = sum(1 for _ in output.open(encoding="utf-8", errors="replace"))
    log.info("Hardware trace: %s (%d lines; run files in %s)", output, lines, work_dir)
    return output
