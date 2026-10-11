"""The VIOMapper loop: Encoder -> CodeGen -> compile -> run -> Verifier -> RCA.

:func:`run_pipeline` calls the same stage functions as the ``encode``,
``codegen``, ``verify`` and ``rca`` commands, round after round, until the
emulated run matches the hardware trace or ``max_rounds`` is reached. Running
the firmware is passed in as ``run``: it gets the round's models and returns
the trace of the emulated run, so the loop does not depend on how the
firmware is started or driven.

Each round is recorded in ``<work>/pipeline.json``; prompts, LLM answers and
verification results stay in the work directory as with the commands.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from boardrunner.errors import BoardRunnerError
from boardrunner.viomapper.ablations import Ablations
from boardrunner.viomapper.codegen.prompt import remove_prompts, write_initial_prompt
from boardrunner.viomapper.codegen.synthesize import synthesize
from boardrunner.viomapper.encoder.encode import (
    DEFAULT_ISR_WINDOW,
    DEFAULT_METHOD,
    DEFAULT_N,
    ENCODER_DIR,
    encode,
)
from boardrunner.viomapper.rca.rca import write_revision_prompt
from boardrunner.viomapper.verifier.verify import verify

log = logging.getLogger(__name__)

RESULT_FILE = "pipeline.json"
DEFAULT_MAX_ROUNDS = 10


@dataclass(frozen=True)
class ModelSpec:
    """One model the pipeline learns: its name, the source file CodeGen
    writes, and the peripheral(s) whose traces it is learned from."""

    name: str
    output: str
    peripherals: Sequence[str]
    model_sources: Sequence[str] = ()


@dataclass(frozen=True)
class RunRequest:
    """What ``run`` gets each round."""

    round: int
    models: Dict[str, str]  # model name -> source file
    build_dir: str          # where --compile put <name>.so
    work_dir: str


RunStep = Callable[[RunRequest], str]


@dataclass
class Round:
    round: int
    prompts: List[str]
    llm_attempts: int
    emulation_log: str
    match: bool
    mismatching: List[str]


@dataclass
class PipelineResult:
    work_dir: str
    match: bool
    rounds: List[Round] = field(default_factory=list)

    def save(self):
        path = Path(self.work_dir) / RESULT_FILE
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path


def _model_dir(work_dir, name):
    """``<work>_<model>``: a model's own prompt folder (as RCA's per-model split)."""
    return work_dir.parent / f"{work_dir.name}_{name}"


def run_pipeline(hardware_log, work_dir, *, models: Sequence[ModelSpec], svd, run: RunStep, client, settings,
                 contract, model_sources_map: Optional[Dict[str, List[str]]] = None, ablations=Ablations(),
                 compile=True, build_dir="build/models", max_retries=1, max_rounds=DEFAULT_MAX_ROUNDS,
                 evaluate=False, method=DEFAULT_METHOD, n=DEFAULT_N, isr_window=DEFAULT_ISR_WINDOW):
    """Learn ``models`` from ``hardware_log``; return a :class:`PipelineResult`.

    One model gets its initial prompt in ``work_dir``, as with the commands;
    several models (compositional modelling, verified together) get one each
    in ``<work>_<model>``, and the joint correction prompts in ``work_dir``.
    ``svd`` is the encoder's :class:`SvdChoice`, ``client`` / ``settings`` the
    LLM, ``contract`` the LibVIO model contract. The LLM is never asked to
    confirm a retry.
    """
    if not models:
        raise BoardRunnerError("the pipeline needs at least one model")
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    outputs = {spec.name: str(Path(spec.output).resolve()) for spec in models}
    names = list(outputs)
    peripherals = list(dict.fromkeys(p for spec in models for p in spec.peripherals))
    result = PipelineResult(str(work_dir), match=False)

    # -- Encoder, then the initial prompt(s) ---------------------------------
    remove_prompts(work_dir)
    if not ablations.no_encoder:
        encode(hardware_log, work_dir, svd=svd, method=method, n=n, isr_window=isr_window)
    pending = []  # folders whose prompt the next CodeGen call sends
    for spec in models:
        prompt_dir = work_dir if len(models) == 1 else _model_dir(work_dir, spec.name)
        if prompt_dir != work_dir:
            remove_prompts(prompt_dir)
        write_initial_prompt(
            prompt_dir,
            peripherals=spec.peripherals,
            model_name=spec.name if len(spec.peripherals) > 1 else None,
            model_sources=spec.model_sources,
            board=svd.platform,
            no_vio=ablations.no_vio,
            no_encoder=ablations.no_encoder,
            hardware_log=str(hardware_log),
            contract=contract,
            encoder_dir=work_dir / ENCODER_DIR,
        )
        pending.append(prompt_dir)

    for number in range(1, max_rounds + 1):
        log.info("── Round %d/%d ──", number, max_rounds)

        # -- CodeGen ----------------------------------------------------------
        prompts, attempts = [], 0
        for prompt_dir in pending:
            targets = list(outputs.values()) if prompt_dir == work_dir \
                else [outputs[prompt_dir.name[len(work_dir.name) + 1:]]]  # <work>_<model>: that model only
            done = synthesize(str(prompt_dir), targets, client=client, settings=settings, compile=compile,
                              build_dir=build_dir, max_retries=max_retries, evaluate=evaluate,
                              confirm_retry=None)
            prompts.append(done.prompt_path)
            attempts += done.attempts

        # -- Run, then Verifier ---------------------------------------------------
        emulation_log = run(RunRequest(number, dict(outputs), str(build_dir), str(work_dir)))
        verified = verify(hardware_log, emulation_log, work_dir, models=outputs, peripherals=peripherals,
                          svd=svd, model_names=names, method=method, n=n, isr_window=isr_window)
        result.rounds.append(Round(number, prompts, attempts, str(emulation_log), verified.match,
                                   [p for p, differs in verified.mismatches.items() if differs]))
        result.save()
        if verified.match:
            log.info("Round %d: the emulated run matches the hardware trace.", number)
            result.match = True
            break

        # -- RCA ----------------------------------------------------------------
        written = write_revision_prompt(work_dir, ablations=ablations, model_sources_map=model_sources_map,
                                        contract=contract)
        if not written:
            raise BoardRunnerError("the Verifier reported a mismatch but RCA wrote no prompt")
        pending = sorted({Path(p).parent for p in written})
    else:
        log.warning("No match after %d round(s).", max_rounds)

    result.save()
    return result


def firmware_run_step(config, *, seconds, stimulus=None, devices: Optional[Dict[str, str]] = None, svd=None):
    """A :data:`RunStep` that runs ``config`` on FastDyn with the round's models.

    Each model is loaded by the device of the same name in lower case
    (``USART2`` -> ``[Device.usart2]``) unless ``devices`` maps it to another;
    its library is ``<build_dir>/<source stem>.so``, where CodeGen's compile
    step put it. Each round runs in ``<work>/runs/round_<N>``.
    """
    from boardrunner.firmware import run_firmware

    devices = dict(devices or {})

    def step(request: RunRequest) -> str:
        scrolls = {devices.get(name, name.lower()): str(Path(request.build_dir) / (Path(source).stem + ".so"))
                   for name, source in request.models.items()}
        missing = [path for path in scrolls.values() if not Path(path).is_file()]
        if missing:
            raise BoardRunnerError("model library not built: " + ", ".join(missing))
        outcome = run_firmware(config, Path(request.work_dir) / "runs" / f"round_{request.round}",
                               seconds=seconds, stimulus=stimulus, scrolls=scrolls, svd=svd)
        return str(outcome.trace)

    return step
