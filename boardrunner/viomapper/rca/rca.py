"""RCA stage: turn the Verifier's results into the next prompt.

Reads ``<work>/verify/verify.json`` and writes ``<work>/revised_prompt.txt``
(SEARCH/REPLACE corrections), or ``<work>/initial_prompt.txt`` when an
ablation asks for a full regeneration. In the --no-rca and --no-verifier
ablations a model composed of several parts gets one prompt per model, in
sibling folders ``<work>_<model>``.
"""

import logging
import os
from pathlib import Path

from fastdyn.utils import parse_config

from boardrunner.errors import RcaError, VerifierError
from boardrunner.viomapper.ablations import Ablations, blind_retry_prompt
from boardrunner.viomapper.codegen.prompt import remove_prompts
from boardrunner.viomapper.codegen.prompts import prompt_gen
from boardrunner.viomapper.codegen.synthesize import INITIAL_PROMPT
from boardrunner.viomapper.rca import prompts
from boardrunner.viomapper.verifier import verifier
from boardrunner.viomapper.verifier.verify import VerifyResult

log = logging.getLogger(__name__)


def _peripheral_ranges(svd_file, peripheral):
    """Address ranges of ``peripheral`` in the SVD, for filtering raw traces (A1)."""
    ranges = []
    for p in parse_config.get_svd_device(svd_file).peripherals:
        if p.name.upper() == peripheral.upper():
            size = 0x400
            if hasattr(p, 'address_block') and p.address_block:
                size = p.address_block.size
            ranges.append((p.base_address, p.base_address + size))
    return ranges


def write_revision_prompt(work_dir, *, ablations=Ablations(), model_sources_map=None, contract=None):
    """Write the prompt for the next CodeGen round; return the written paths.

    Returns an empty list when every peripheral matched (nothing to correct).
    """
    try:
        result = VerifyResult.load(work_dir)
    except VerifierError as e:
        raise RcaError(str(e)) from e
    if result.match:
        log.info("Every peripheral matches the hardware: no correction prompt needed.")
        return []

    remove_prompts(work_dir)
    work_dir = str(work_dir)
    peripherals = result.peripherals
    model_to_path = result.models
    if ablations.active():
        log.info("Ablations: %s", ", ".join(ablations.active()))

    if len(peripherals) > 1:
        written = prompts.iteration_prompt_gen_multiple_periph(
            cm_path_hardware=result.hardware_dir,
            cm_path_emulation=result.emulation_dir,
            peripherals=peripherals,
            model_names=result.model_names,
            model_to_path=model_to_path,
            out_dir=work_dir,
            no_encoder=ablations.no_encoder,
            no_rca=ablations.no_rca,
            no_verifier=ablations.no_verifier,
            no_vio=ablations.no_vio,
            hardware_log=result.hardware_log,
            emulation_log=result.emulation_log,
            model_sources_map=model_sources_map or None,
            contract=contract,
        )
        if written is None:
            return []
        return [Path(p) for p in (written.values() if isinstance(written, dict) else [written])]

    peripheral = peripherals[0]
    model_path = list(model_to_path.values())[0]
    _, diff_obj = verifier.verify_automata(result.hardware_dir, result.emulation_dir, peripheral)

    if ablations.no_verifier:
        # A4: the original encoder-based prompt + the broken model + "fix it";
        # no emulation trace, no diffs.
        log.warning("--no-verifier: generating blind retry prompt.")
        periph_dir = os.path.join(result.hardware_dir, peripheral)
        original_prompt = prompt_gen.generate_prompt(periph_dir, contract=contract) \
            if os.path.isdir(periph_dir) else ""
        try:
            model_source = Path(model_path).read_text(encoding="utf-8")
        except OSError as e:
            raise RcaError(f"cannot read the model {model_path}: {e}") from e
        path = Path(work_dir) / INITIAL_PROMPT
        path.write_text(blind_retry_prompt(original_prompt, model_source), encoding="utf-8")
        log.info("No-verifier retry prompt written to %s", path)
        return [path]

    common = dict(diff_obj=diff_obj, device_model_path=model_path, peripheral=peripheral,
                  out_dir=work_dir, no_vio=ablations.no_vio, contract=contract)
    if ablations.no_rca:
        # A2: the Verifier's diffs, but no RCA analysis; full regeneration.
        log.warning("--no-rca: generating prompt with Verifier diffs but no RCA analysis.")
        written = prompts.iteration_prompt_gen(no_rca=True, **common)
    elif ablations.no_encoder:
        # A1: raw traces instead of the encoder analysis; SEARCH/REPLACE kept.
        log.warning("--no-encoder: generating correction prompt with raw traces.")
        written = prompts.iteration_prompt_gen(
            no_encoder=True,
            hardware_log=result.hardware_log,
            emulation_log=result.emulation_log,
            peripheral_ranges=_peripheral_ranges(result.svd_file, peripheral),
            **common,
        )
    else:
        written = prompts.iteration_prompt_gen(**common)
    return [Path(written)]
