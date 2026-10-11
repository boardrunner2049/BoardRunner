"""Verifier stage: compare the emulated model's trace with the hardware trace.

Both traces are encoded into ``<work>/verify/`` (``out_cm`` and
``emulation``) and compared peripheral by peripheral. ``verify.json`` there
records the inputs, the result per peripheral and the differences found, for
RCA and for people.
"""

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List

from boardrunner.errors import VerifierError
from boardrunner.viomapper.encoder.encode import (
    DEFAULT_ISR_WINDOW,
    DEFAULT_METHOD,
    DEFAULT_N,
    ENCODER_DIR,
    check_peripherals,
    encode,
)
from boardrunner.viomapper.verifier import verifier

log = logging.getLogger(__name__)

VERIFY_DIR = "verify"
EMULATION_DIR = "emulation"
RESULT_FILE = "verify.json"


@dataclass
class VerifyResult:
    """What was compared and whether each peripheral matched."""

    work_dir: str
    hardware_log: str
    emulation_log: str
    svd_file: str
    platform: str
    peripherals: List[str]
    models: Dict[str, str]  # model name -> source file
    model_names: List[str]
    hardware_dir: str
    emulation_dir: str
    mismatches: Dict[str, bool] = field(default_factory=dict)  # peripheral -> True if it differs
    differences: Dict[str, dict] = field(default_factory=dict)  # peripheral -> the verifier's diff fields

    @property
    def match(self):
        return not any(self.mismatches.values())

    @property
    def path(self):
        return Path(self.work_dir) / VERIFY_DIR / RESULT_FILE

    def save(self):
        self.path.write_text(json.dumps(asdict(self), indent=2, default=str) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, work_dir):
        path = Path(work_dir) / VERIFY_DIR / RESULT_FILE
        if not path.is_file():
            raise VerifierError(f"no verification results in {path}: run `boardrunner verify` first")
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def _diff_fields(diff):
    return {k: v for k, v in vars(diff).items() if v not in (None, [], {}, "")}


def verify(hardware_log, emulation_log, work_dir, *, models, peripherals, svd, model_names=(),
           method=DEFAULT_METHOD, n=DEFAULT_N, isr_window=DEFAULT_ISR_WINDOW):
    """Encode both traces, compare ``peripherals`` and save ``verify.json``.

    ``models`` maps each model name to its source file (RCA shows the source
    to the LLM); ``svd`` is the encoder's :class:`SvdChoice`. Returns a
    :class:`VerifyResult`; ``result.match`` is True when every peripheral's
    behaviour matches the hardware.
    """
    if not peripherals:
        raise VerifierError("nothing to compare: pass the peripheral(s) with -p")
    if not models:
        raise VerifierError("no model given: pass -d NAME:PATH")
    for name, path in models.items():
        if not os.path.isfile(path):
            raise VerifierError(f"model file for '{name}' not found: {path}")
    for name in model_names:
        if name not in models:
            raise VerifierError(f"no -d entry for model '{name}': add -d {name}:/path/to/model.c")

    verify_dir = Path(work_dir) / VERIFY_DIR
    if verify_dir.exists():
        shutil.rmtree(verify_dir)
    verify_dir.mkdir(parents=True)

    options = dict(svd=svd, method=method, n=n, isr_window=isr_window)
    hardware_dir = encode(hardware_log, verify_dir, name=ENCODER_DIR, **options)
    check_peripherals(hardware_dir, peripherals, what="hardware")
    emulation_dir = encode(emulation_log, verify_dir, name=EMULATION_DIR, **options)
    for periph in peripherals:
        if not (emulation_dir / periph).is_dir():
            log.warning("Peripheral %s is not in the emulation trace: emulation likely crashed early.", periph)

    result = VerifyResult(
        work_dir=str(Path(work_dir).resolve()),
        hardware_log=str(Path(hardware_log).resolve()),
        emulation_log=str(Path(emulation_log).resolve()),
        svd_file=svd.path,
        platform=svd.platform,
        peripherals=list(peripherals),
        models={name: str(Path(path).resolve()) for name, path in models.items()},
        model_names=list(model_names),
        hardware_dir=str(hardware_dir),
        emulation_dir=str(emulation_dir),
    )
    for periph in peripherals:
        not_match, diff = verifier.verify_automata(str(hardware_dir), str(emulation_dir), periph)
        result.mismatches[periph] = bool(not_match)
        result.differences[periph] = _diff_fields(diff)
        if not_match:
            log.warning("%s: emulation differs from the hardware", periph)
        else:
            log.info("%s: emulation matches the hardware", periph)
    result.save()
    log.info("Verification results written to %s", result.path)
    return result
