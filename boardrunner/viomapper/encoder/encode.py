"""Encoder stage: a hardware (or emulation) MMIO trace -> the encoder output.

The encoder output is a folder with one subfolder per peripheral seen in the
trace (initialization sequence, loop patterns, entropy, read-modify-write and
ISR analysis) and a ``summary.txt``. CodeGen builds the initial prompt from
it, and the Verifier compares the hardware and emulation outputs.
"""

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastdyn import paths
from fastdyn.utils import parse_config

from boardrunner.errors import EncoderError
from boardrunner.viomapper.encoder import context_minimizer

log = logging.getLogger(__name__)

ENCODER_DIR = "out_cm"
DEFAULT_METHOD = "ngram"
DEFAULT_N = 2
DEFAULT_ISR_WINDOW = 10000000


@dataclass(frozen=True)
class SvdChoice:
    """The SVD file a trace is decoded with, and the platform name it gives."""

    path: str
    key: str
    platform: str
    device: object


def resolve_svd(board=None, svd=None):
    """Find the CMSIS-SVD file for ``board`` (or use ``svd``) and parse it.

    ``svd`` may be a file or a folder of SVD files; without it FastDyn's
    bundled SVD collection is searched. A folder needs ``board``.
    """
    platform = (board or "").strip()
    svd_input = svd if svd is not None else paths.default_svd_dir()
    if not platform and svd is None:
        raise EncoderError("the board is required when no SVD file is given: pass --board")
    if not platform and svd_input and os.path.isdir(os.path.expanduser(svd_input)):
        raise EncoderError("the board is required when --svd is a folder: pass --board or an SVD file")
    try:
        svd_file, svd_key = parse_config.resolve_svd(
            platform_or_board=platform or "unused",
            svd=svd_input,
            default_dir=None,
            auto_discover=False,
        )
    except parse_config.SvdResolutionError as e:
        raise EncoderError(str(e)) from e
    log.info("Using SVD: %s (key='%s')", svd_file, svd_key)
    return SvdChoice(svd_file, svd_key, platform, parse_config.get_svd_device(svd_file))


def encode(trace, out_dir, *, svd, name=ENCODER_DIR, method=DEFAULT_METHOD, n=DEFAULT_N,
           isr_window=DEFAULT_ISR_WINDOW):
    """Encode ``trace`` into ``out_dir/name`` and return that folder.

    The folder is replaced, so no file from an earlier encoding is left
    behind (a stale ``loop_pattern_N.txt`` would end up in the prompt).
    ``svd`` is the :class:`SvdChoice` from :func:`resolve_svd`.
    """
    if not os.path.isfile(trace):
        raise EncoderError(f"trace file not found: {trace}")
    target = Path(out_dir) / name
    if target.exists():
        shutil.rmtree(target)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    return Path(context_minimizer.minimize_context(
        out_dir=str(out_dir),
        log_file=str(trace),
        platform=svd.platform,
        method=method,
        peripheral=None,  # unused: every peripheral in the trace is encoded
        n=n,
        svd_device=svd.device,
        isr_window=isr_window,
        cm_dir_name=name,
    ))


def check_peripherals(encoder_dir, peripherals, *, what="hardware"):
    """Raise if a requested peripheral has no folder in the encoder output."""
    missing = [p for p in peripherals if not (Path(encoder_dir) / p).is_dir()]
    if missing:
        found = sorted(p.name for p in Path(encoder_dir).iterdir() if p.is_dir())
        raise EncoderError(
            f"peripheral(s) {', '.join(missing)} not in the {what} trace; it has: {', '.join(found) or 'none'}")
