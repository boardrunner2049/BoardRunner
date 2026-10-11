"""CodeGen stage, prompt half: write the initial prompt into the work directory.

Three kinds of initial prompt:

* from the Encoder's output (``<work>/out_cm``), for one peripheral or a
  model composed from several (``model_name`` and ``model_sources``);
* from the raw hardware trace (``no_encoder``, ablation A1);
* for a slave model on an SPI or I2C bus, from the slave's firmware source
  and a reference model (``slave``).
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from boardrunner.errors import CodegenError
from boardrunner.viomapper.codegen.prompts import prompt_gen
from boardrunner.viomapper.codegen.synthesize import INITIAL_PROMPT, REVISED_PROMPT
from boardrunner.viomapper.encoder.encode import ENCODER_DIR

log = logging.getLogger(__name__)


@dataclass
class SlaveSources:
    """What a slave-model prompt is built from."""

    firmware_code: str
    reference_model: str


def write_initial_prompt(work_dir, *, peripherals: Sequence[str], model_name: Optional[str] = None,
                         model_sources: Sequence[str] = (), board: Optional[str] = None,
                         no_vio=False, no_encoder=False, hardware_log=None,
                         slave: Optional[SlaveSources] = None, contract=None, encoder_dir=None):
    """Write ``<work_dir>/initial_prompt.txt`` and return its path.

    The encoder output is ``<work_dir>/out_cm`` unless ``encoder_dir`` says
    otherwise (the pipeline writes one prompt folder per model).

    A ``revised_prompt.txt`` left from an earlier round is removed, so the
    next LLM call uses this prompt.
    """
    if not peripherals:
        raise CodegenError("the prompt needs the peripheral(s) to model: pass -p")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    peripherals = list(peripherals)
    model_sources = list(model_sources or ())

    if slave is not None:
        if not board:
            raise CodegenError("a slave-model prompt needs the board: pass -b")
        slave_type = "spi" if any("spi" in p.lower() for p in peripherals) else "i2c"
        path = prompt_gen.slave_model_gen(
            peripheral_name=", ".join(peripherals),
            platform_name=board,
            out_dir=str(work_dir),
            slave_firmware_path=slave.firmware_code,
            reference_model_path=slave.reference_model,
            slave_type=slave_type,
            contract=contract,
        )
    elif no_encoder:
        # Ablation A1: skip the Encoder; the prompt carries the raw I/O trace.
        if not hardware_log or not board:
            raise CodegenError("--no-encoder builds the prompt from the raw trace: pass -hw and -b")
        log.info("Ablation mode: --no-encoder enabled. Skipping Encoder, using raw I/O trace.")
        prompt = prompt_gen.generate_prompt_no_encoder(
            hardware_log=hardware_log,
            peripheral_name=peripherals[0],
            platform_name=board.strip(),
            no_vio=no_vio,
            model_name=model_name,
            model_sources=model_sources,
            contract=contract,
        )
        path = work_dir / INITIAL_PROMPT
        path.write_text(prompt + "\n", encoding="utf-8")
        log.info("Ablation prompt (no encoder) written to %s", path)
    else:
        encoder_dir = Path(encoder_dir) if encoder_dir else work_dir / ENCODER_DIR
        if not encoder_dir.is_dir():
            raise CodegenError(f"no encoder output in {encoder_dir}: run `boardrunner encode` first "
                               "(or pass --no-encoder)")
        missing = [p for p in peripherals if not (encoder_dir / p).is_dir()]
        if missing:
            raise CodegenError(f"peripheral(s) {', '.join(missing)} not in the encoder output {encoder_dir}")
        if len(peripherals) > 1:
            # One model composed from several peripherals' traces.
            if not model_name:
                raise CodegenError("a model built from several peripherals needs a name: pass -mname")
            unknown = [s for s in model_sources if s not in peripherals]
            if unknown:
                raise CodegenError(f"--model-source {', '.join(unknown)} is not among the peripherals "
                                   f"{', '.join(peripherals)} (pass it with -p too)")
            path = prompt_gen.initial_prompt_gen_multiple_periphs(
                analysis_dir=str(encoder_dir),
                model_name=model_name,
                peripherals=peripherals,
                model_sources=model_sources or None,  # None lets the prompt pick the sources by name
                out_dir=str(work_dir),
                no_vio=no_vio,
                contract=contract,
            )
        else:
            path = prompt_gen.initial_prompt_gen(
                analysis_dir=str(encoder_dir),
                peripheral=peripherals[0],
                out_dir=str(work_dir),
                no_vio=no_vio,
                contract=contract,
            )

    stale = work_dir / REVISED_PROMPT
    if stale.exists():
        stale.unlink()
        log.info("Removed %s from an earlier round", stale)
    return Path(path)


def remove_prompts(work_dir):
    """Remove the prompts derived from an earlier encoding or verification."""
    for name in (INITIAL_PROMPT, REVISED_PROMPT):
        path = os.path.join(work_dir, name)
        if os.path.exists(path):
            os.remove(path)
            log.info("Removed %s (made from earlier results)", path)
