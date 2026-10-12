"""The ``boardrunner`` command: one subcommand per VIOMapper stage (paper Fig. 7).

    encode   hardware trace -> encoder output
    codegen  initial or revised prompt -> LLM -> model (-> compiled model)
    verify   hardware trace vs. emulation trace -> per-peripheral result
    rca      verification results -> revised prompt for the next codegen

``run`` and ``build-models`` are FastDyn's own commands. The stages live in
``boardrunner.viomapper``; this module only turns options into calls.
Exit status: 0 success (``verify``: the traces match), 1 ``verify`` found a
mismatch, 2 an error.
"""

import logging
import shutil
import sys
from pathlib import Path

import click

from fastdyn import logs

from . import __version__
from .errors import BoardRunnerError

log = logging.getLogger(__name__)


def _log_settings(verbose, quiet, log_levels):
    """Turn -v/-q/--log-level into a default level and per-logger levels."""
    if verbose and quiet:
        raise click.UsageError("-v/--verbose and -q/--quiet cannot be combined.")
    default = "DEBUG" if verbose else "WARNING" if quiet else None
    overrides = {}
    for option in log_levels:
        name, separator, level = option.rpartition("=")
        try:
            logs.level_number(level)
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--log-level") from exc
        if separator:
            overrides[name] = level
        else:
            default = level
    return default, overrides


class _StepFailed(click.ClickException):
    exit_code = 2


class _Group(click.Group):
    """Report a BoardRunnerError as ``Error: ...`` with exit status 2."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except BoardRunnerError as e:
            raise _StepFailed(str(e)) from e


@click.group(cls=_Group)
@click.version_option(prog_name="BoardRunner", version=__version__)
@click.option('-v', '--verbose', is_flag=True, help='Show debug messages.')
@click.option('-q', '--quiet', is_flag=True, help='Show only warnings and errors.')
@click.option('--log-level', 'log_levels', multiple=True, metavar='[LOGGER=]LEVEL',
              help='Set the log level, or one logger\'s level (e.g. boardrunner.viomapper=DEBUG). Repeatable. '
                   'The default comes from FASTDYN_LOG_LEVEL, else INFO.')
@click.option('--log-file', type=click.Path(dir_okay=False, writable=True), default=None,
              help='Also write every log message (DEBUG and above) to this file.')
def cli(verbose, quiet, log_levels, log_file):
    """BoardRunner: learn peripheral models from a hardware trace and rehost firmware on FastDyn.

    A round by hand: `encode` once, then `codegen` -> `run` -> `verify` -> `rca`
    -> `codegen` ... until `verify` reports a match.
    """
    default, overrides = _log_settings(verbose, quiet, log_levels)
    logs.configure(level=default, levels=overrides, log_file=log_file, namespaces=("boardrunner", "fastdyn"))


# ── Shared options ────────────────────────────────────────────────────────────

def _contract_dir_option(f):
    return click.option(
        '--contract-dir',
        type=click.Path(file_okay=False, exists=True, resolve_path=True),
        default=None,
        metavar='PATH',
        help='LibVIO model contract directory (API summary, host functions) for the prompts. '
             'Default: $VIO_CONTRACT_DIR, else `pkg-config --variable=contractdir vio`.'
    )(f)


def _load_contract(contract_dir):
    from .viomapper.codegen.prompts.contract import load_contract
    contract = load_contract(contract_dir)
    log.info("Using the LibVIO model contract %s from %s", contract.version, contract.directory)
    return contract


def _encoder_options(f):
    """The options that decide how a trace is encoded (encode and verify)."""
    from .viomapper.encoder.encode import DEFAULT_ISR_WINDOW, DEFAULT_METHOD, DEFAULT_N
    options = [
        click.option('-b', '--board', type=str, default=None,
                     help='Name of the platform the firmware ran on; picks the CMSIS-SVD file.'),
        click.option('-s', '--svd', type=click.Path(resolve_path=True, exists=True), default=None,
                     metavar='PATH', help='An SVD file, or a folder of them (then --board picks one).'),
        click.option('--method', default=DEFAULT_METHOD, show_default=True,
                     type=click.Choice(['ngram', 'window', 'other'], case_sensitive=False),
                     help='Loop pattern mining method.'),
        click.option('--n', type=int, default=DEFAULT_N, show_default=True,
                     help='Value of n for the n-gram method.'),
        click.option('--isr-window', type=int, default=DEFAULT_ISR_WINDOW, show_default=True,
                     help='ISR window size.'),
    ]
    for option in reversed(options):
        f = option(f)
    return f


def _work_dir_out_option(f):
    f = click.option('--clean', is_flag=True, default=False,
                     help='Delete the whole work directory first (by default only this command\'s own '
                          'output in it is replaced).')(f)
    return click.option('-o', '--work-dir', default='./fastdyn_work', show_default=True, metavar='PATH',
                        type=click.Path(resolve_path=True, file_okay=False),
                        help='Work directory.')(f)


def _prepare_work_dir(work_dir, clean):
    path = Path(work_dir)
    if clean and path.exists():
        log.info("--clean: deleting %s", path)
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


_ABLATION_HELP = {
    'no_encoder': {
        'codegen': 'Ablation A1: build the prompt from the raw hardware trace (-hw) instead of the '
                   'encoder output.',
        'rca': 'Ablation A1: correction prompt with the raw traces instead of the encoder analysis.'},
    'no_vio': {
        'codegen': 'Ablation A3: leave LibVIO\'s API and the LibVIO-only model rules out of the prompt, '
                   'so only the emulator\'s host functions are offered.',
        'rca': 'Ablation A3: leave LibVIO\'s API and the LibVIO-only model rules out of the correction '
               'prompt.'},
    'no_rca': {
        'rca': 'Ablation A2: show the Verifier\'s diffs but no RCA analysis, and ask for a full '
               'regeneration (initial_prompt.txt) instead of SEARCH/REPLACE corrections.'},
    'no_verifier': {
        'rca': 'Ablation A4: no Verifier feedback; retry with the original prompt, the broken model and a '
               'generic request to fix it.'},
}


def _ablation_options(stage):
    """The ablation switches that apply to ``stage``."""
    def decorate(f):
        for name in ('no_verifier', 'no_rca', 'no_vio', 'no_encoder'):
            if stage in _ABLATION_HELP[name]:
                f = click.option('--' + name.replace('_', '-'), name, is_flag=True, default=False,
                                 help=_ABLATION_HELP[name][stage])(f)
        return f
    return decorate


def _parse_pairs(entries, separator, option, form, example):
    pairs = {}
    for entry in entries:
        name, sep, value = (part.strip() for part in entry.partition(separator))
        if not sep or not name or not value:
            raise click.BadParameter(f"'{entry}' must be in {form} format, e.g. {example}", param_hint=option)
        pairs[name] = value
    return pairs


_LLM_OPTIONS = [
    click.option('--model', default='gpt-4o', show_default=True, type=str, help='Model name to use.'),
    click.option('--model-provider', default='openai', show_default=True,
                 type=click.Choice(['openai', 'ollama'], case_sensitive=False), help='LLM provider backend.'),
    click.option('--env-file', default='~/.fastdyn.env', show_default=True, type=str,
                 help='Path to .env file containing OPENAI_API_KEY.'),
    click.option('--temperature', default=0.2, show_default=True, type=float,
                 help='Sampling temperature. For Ollama, the default is 0.1 unless this option is explicitly set.'),
    click.option('--reasoning-effort', type=click.Choice(["none", "minimal", "low", "medium", "high", "xhigh"]),
                 default=None, help='Reasoning effort for supported gpt-5 and o-series models.'),
    click.option('--stateless/--no-stateless', default=True, show_default=True,
                 help='Keep (--stateless) or strip (--no-stateless) the conversation reset line in prompts.'),
    click.option('--max-retries', default=1, show_default=True, type=int,
                 help='Maximum number of follow-up requests after a parse, patch or compile failure.'),
    click.option('--evaluate/--no-evaluate', default=False, show_default=True,
                 help='Write per-call metrics to fastdyn_llm_history/metrics.jsonl.'),
    click.option('--ollama-url', default='http://127.0.0.1:11434', show_default=True, type=str,
                 help='Base URL for the Ollama HTTP server. Use SSH port forwarding for remote servers.'),
    click.option('--ollama-num-ctx', default=262144, show_default=True, type=int,
                 help='Ollama num_ctx option. Set to 0 to use the server/model default.'),
    click.option('--ollama-timeout', default=1800.0, show_default=True, type=float,
                 help='Timeout in seconds for non-streaming Ollama requests.'),
]

_BUILD_DIR_OPTION = click.option(
    '--build-dir', default='build/models', show_default=True, type=click.Path(resolve_path=True, file_okay=False),
    metavar='PATH', help='Where the models are compiled to (<name>.so for each <name>.c).')


def _llm_options(f):
    """The options that choose and drive the LLM (codegen and pipeline)."""
    for option in reversed(_LLM_OPTIONS):
        f = option(f)
    return f


def _llm_settings(ctx, model, model_provider, env_file, temperature, reasoning_effort, stateless,
                  ollama_url, ollama_num_ctx, ollama_timeout):
    from .viomapper.codegen.synthesize import LlmSettings
    return LlmSettings(
        model=model,
        provider=model_provider,
        env_file=env_file,
        temperature=None if _is_default(ctx, 'temperature') else temperature,
        reasoning_effort=reasoning_effort,
        stateless=stateless,
        ollama_url=ollama_url,
        ollama_num_ctx=ollama_num_ctx,
        ollama_timeout=ollama_timeout,
    )


# ── encode ────────────────────────────────────────────────────────────────────

@cli.command('encode', help='Encoder: turn a hardware MMIO trace into the encoder output (<work>/out_cm), '
                            'one folder per peripheral, for `codegen`.')
@click.option('-hw', '--hardware-log', required=True, type=click.Path(resolve_path=True, exists=True,
              dir_okay=False), metavar='PATH', help='The trace recorded with the firmware on the hardware.')
@_encoder_options
@_work_dir_out_option
def encode_command(hardware_log, board, svd, method, n, isr_window, work_dir, clean):
    from .viomapper.codegen.prompt import remove_prompts
    from .viomapper.encoder.encode import encode, resolve_svd

    svd_choice = resolve_svd(board, svd)
    _prepare_work_dir(work_dir, clean)
    remove_prompts(work_dir)
    encoder_dir = encode(hardware_log, work_dir, svd=svd_choice, method=method, n=n, isr_window=isr_window)
    peripherals = sorted(p.name for p in encoder_dir.iterdir() if p.is_dir())
    log.info("Encoder output in %s: %s", encoder_dir, ", ".join(peripherals) or "no peripherals")


# ── codegen ───────────────────────────────────────────────────────────────────

@cli.command('codegen', help='CodeGen: send the work directory\'s prompt to an LLM and write the model '
                             '(initial_prompt.txt) or patch it (revised_prompt.txt, from `rca`). Without a '
                             'prompt, the initial prompt is built first from the encoder output.')
@click.option('-d', '--work-dir', required=True, type=click.Path(resolve_path=True, file_okay=False),
              metavar='PATH', help='Work directory with the encoder output or a prompt.')
@click.option('-o', '--output', multiple=True, type=click.Path(resolve_path=True), metavar='PATH',
              help='Model .c file(s) to write or patch. Repeatable.')
@click.option('--prompt-only', is_flag=True, default=False,
              help='Write initial_prompt.txt (replacing an existing one) and stop, e.g. to read or edit it '
                   'before the LLM call.')
@click.option('-p', '--peripheral', 'peripherals', type=str, multiple=True,
              help='Peripheral(s) to model (initial prompt). Repeatable.')
@click.option('-mname', '--model-name', type=str, default=None,
              help='Name of the model; required when it covers several peripherals.')
@click.option('-ms', '--model-source', 'model_sources', type=str, multiple=True,
              help='Peripheral(s) whose trace is the primary source for the model, when -mname does not '
                   'name them. Example: -ms DMA1 -ms DMAMUX1')
@click.option('-b', '--board', type=str, default=None,
              help='Platform name (for --no-encoder and slave-model prompts).')
@click.option('-hw', '--hardware-log', type=click.Path(resolve_path=True, exists=True, dir_okay=False),
              metavar='PATH', help='Hardware trace (for --no-encoder).')
@click.option('-sm', '--slave-model', is_flag=True, default=False,
              help='Build a prompt for a slave model on an SPI or I2C bus (needs -rm, -fc, -b, -p).')
@click.option('-rm', '--reference-model', type=click.Path(resolve_path=True, exists=True), metavar='PATH',
              help='Reference slave model (for -sm).')
@click.option('-fc', '--firmware-code', type=click.Path(resolve_path=True, exists=True), metavar='PATH',
              help='The slave firmware\'s source code (for -sm).')
@_ablation_options('codegen')
@_contract_dir_option
@_llm_options
@click.option('--compile/--no-compile', default=False, show_default=True,
              help='Compile the model(s) after writing/patching, with FastDyn\'s model builder.')
@_BUILD_DIR_OPTION
@click.option('-y', '--yes', is_flag=True, default=False,
              help='Retry without asking (otherwise asked in a terminal, and not retried elsewhere).')
@click.pass_context
def codegen_command(ctx, work_dir, output, prompt_only, peripherals, model_name, model_sources, board,
                    hardware_log, slave_model, reference_model, firmware_code, no_vio, no_encoder,
                    contract_dir, model, model_provider, env_file, temperature, reasoning_effort, stateless,
                    compile, build_dir, max_retries, yes, evaluate, ollama_url, ollama_num_ctx, ollama_timeout):
    from .viomapper.codegen.prompt import SlaveSources, write_initial_prompt
    from .viomapper.codegen.synthesize import make_client, select_prompt, synthesize

    if slave_model and (reference_model is None or firmware_code is None):
        raise click.UsageError("--slave-model needs --reference-model and --firmware-code.")
    prompt_options = [name for name, given in (
        ('-p', peripherals), ('-mname', model_name), ('-ms', model_sources), ('-hw', hardware_log),
        ('-sm', slave_model), ('--no-encoder', no_encoder), ('--no-vio', no_vio)) if given]

    selected = None if prompt_only else select_prompt(work_dir)
    if selected is None:
        write_initial_prompt(
            work_dir,
            peripherals=peripherals,
            model_name=model_name,
            model_sources=model_sources,
            board=board,
            no_vio=no_vio,
            no_encoder=no_encoder,
            hardware_log=hardware_log,
            slave=SlaveSources(firmware_code, reference_model) if slave_model else None,
            contract=_load_contract(contract_dir),
        )
        if prompt_only:
            return
    elif prompt_options:
        log.warning("Using the existing %s; %s only apply when the prompt is built (use --prompt-only "
                    "to rebuild it).", Path(selected[0]).name, ", ".join(prompt_options))

    if not output:
        raise click.UsageError("Missing option '-o' / '--output': the model file(s) to write or patch.")
    settings = _llm_settings(ctx, model, model_provider, env_file, temperature, reasoning_effort, stateless,
                             ollama_url, ollama_num_ctx, ollama_timeout)
    synthesize(
        work_dir, list(output),
        client=make_client(settings),
        settings=settings,
        compile=compile,
        build_dir=build_dir,
        max_retries=max_retries,
        evaluate=evaluate,
        confirm_retry=None if yes else _ask_retry,
    )


def _is_default(ctx, name):
    source = ctx.get_parameter_source(name)
    return source is None or source.name == "DEFAULT"


def _ask_retry(question):
    """Ask before a retry in a terminal; elsewhere do not retry (use --yes)."""
    if not sys.stdin.isatty():
        log.error("Not retrying without a terminal to ask in; pass --yes to retry without asking.")
        return False
    # Builtin input() rather than click.confirm, which can hang on some TTYs.
    return input(f"{question} [Y/n]: ").strip().lower() in ("", "y", "yes")


# ── verify ────────────────────────────────────────────────────────────────────

@cli.command('verify', help='Verifier: compare the trace of a run with the model(s) against the hardware '
                            'trace. Exit status 0: they match; 1: they differ (then run `rca`).')
@click.option('-hw', '--hardware-log', required=True, type=click.Path(resolve_path=True, exists=True,
              dir_okay=False), metavar='PATH', help='The trace recorded with the firmware on the hardware.')
@click.option('-em', '--emulation-log', required=True, type=click.Path(resolve_path=True, exists=True,
              dir_okay=False), metavar='PATH', help='The trace of the emulated run with the model(s).')
@click.option('-d', '--device-model', 'device_models', type=str, multiple=True, required=True,
              metavar='NAME:PATH', help='Model name and source file. Repeatable. '
              'Example: -d ADC1:model.c -d DMA_with_DMAMUX1:model2.c')
@click.option('-mname', '--model-name', 'model_names', type=str, multiple=True,
              help='Name(s) of the model(s) being verified (each needs a -d entry).')
@click.option('-p', '--peripheral', 'peripherals', type=str, multiple=True, required=True,
              help='Peripheral(s) to compare. Repeatable.')
@_encoder_options
@_work_dir_out_option
def verify_command(hardware_log, emulation_log, device_models, model_names, peripherals, board, svd, method,
                   n, isr_window, work_dir, clean):
    from .viomapper.encoder.encode import resolve_svd
    from .viomapper.verifier.verify import verify

    models = _parse_pairs(device_models, ':', '--device-model', 'NAME:PATH', 'ADC1:model.c')
    svd_choice = resolve_svd(board, svd)
    _prepare_work_dir(work_dir, clean)
    result = verify(hardware_log, emulation_log, work_dir, models=models, peripherals=peripherals,
                    svd=svd_choice, model_names=model_names, method=method, n=n, isr_window=isr_window)
    if not result.match:
        log.warning("Mismatch: run `boardrunner rca -d %s` for the correction prompt.", work_dir)
        sys.exit(1)
    log.info("Both hardware log and emulation log matched!")


# ── rca ───────────────────────────────────────────────────────────────────────

@cli.command('rca', help='RCA: turn the results of `verify` into the next prompt: revised_prompt.txt with '
                         'SEARCH/REPLACE corrections (or initial_prompt.txt for --no-rca / --no-verifier).')
@click.option('-d', '--work-dir', required=True, type=click.Path(resolve_path=True, file_okay=False,
              exists=True), metavar='PATH', help='The work directory `verify` wrote to.')
@click.option('--ms-map', 'ms_map', type=str, multiple=True, metavar='MNAME=PERIPH1,PERIPH2,...',
              help='Per-model source peripherals, for --no-rca and --no-verifier with several models (each '
                   'model is then corrected on its own). Repeat once per model. '
                   'Example: --ms-map "ADC=ADC1,ADC2,ADC12_Common"')
@_ablation_options('rca')
@_contract_dir_option
def rca_command(work_dir, ms_map, no_verifier, no_rca, no_vio, no_encoder, contract_dir):
    from .viomapper.ablations import Ablations
    from .viomapper.rca.rca import write_revision_prompt

    sources = {}
    for name, csv in _parse_pairs(ms_map, '=', '--ms-map', 'MNAME=PERIPH1,PERIPH2,...', 'ADC=ADC1,ADC2').items():
        sources[name] = [s.strip() for s in csv.split(',') if s.strip()]
        if not sources[name]:
            raise click.BadParameter(f"the entry for '{name}' lists no peripherals", param_hint='--ms-map')
    written = write_revision_prompt(
        work_dir,
        ablations=Ablations(no_encoder=no_encoder, no_rca=no_rca, no_vio=no_vio, no_verifier=no_verifier),
        model_sources_map=sources,
        contract=_load_contract(contract_dir),
    )
    for path in written:
        log.info("Next prompt: %s", path)


# ── Running firmware: trace and pipeline ──────────────────────────────────────

def _run_options(f):
    from .firmware import DEFAULT_SECONDS
    f = click.option('--stimulus', type=str, default=None, metavar='CMD',
                     help='Shell command that drives the firmware\'s inputs during the run (e.g. types into a '
                          'pseudo-terminal); started just before QEMU, stopped at the end. $FASTDYN_WORK_DIR is '
                          'the run\'s folder.')(f)
    return click.option('--seconds', type=float, default=DEFAULT_SECONDS, show_default=True,
                        help='How long each run lasts.')(f)


@cli.command('trace', help='Hardware in the loop: run the firmware with its peripherals on the real board '
                           '(a passthrough configuration) and save the MMIO trace, the input of `encode`.')
@click.option('-c', '--config', required=True, type=click.Path(resolve_path=True, exists=True, dir_okay=False),
              metavar='PATH', help='FastDyn configuration routing the peripherals to the board (passthrough).')
@click.option('-o', '--output', required=True, type=click.Path(resolve_path=True, dir_okay=False),
              metavar='PATH', help='Where to save the trace.')
@click.option('-w', '--run-dir', type=click.Path(resolve_path=True, file_okay=False), default=None,
              metavar='PATH', help='Folder for the run\'s own files (default: <output>.run).')
@_run_options
def trace_command(config, output, run_dir, seconds, stimulus):
    from .hitl.capture import capture_trace
    capture_trace(config, output, seconds=seconds, stimulus=stimulus, work_dir=run_dir)


@cli.command('pipeline', help='The whole loop, automatically: encode the hardware trace, then codegen -> '
                              'compile -> run -> verify -> rca until the run matches the hardware trace or '
                              '--max-rounds is reached. Writes <work>/pipeline.json.')
@click.option('-hw', '--hardware-log', required=True, type=click.Path(resolve_path=True, exists=True,
              dir_okay=False), metavar='PATH', help='The trace recorded on the hardware (`boardrunner trace`).')
@click.option('-c', '--config', required=True, type=click.Path(resolve_path=True, exists=True, dir_okay=False),
              metavar='PATH', help='FastDyn configuration that runs the firmware with the models (elder).')
@click.option('-d', '--work-dir', default='./fastdyn_work', show_default=True, metavar='PATH',
              type=click.Path(resolve_path=True, file_okay=False), help='Work directory.')
@click.option('-p', '--peripheral', 'peripherals', type=str, multiple=True,
              help='Peripheral(s) the model is learned from (one model). Repeatable.')
@click.option('-o', '--output', type=click.Path(resolve_path=True, dir_okay=False), default=None,
              metavar='PATH', help='The model source file (one model).')
@click.option('-mname', '--model-name', type=str, default=None,
              help='Name of the model (default: the peripheral); required for several peripherals.')
@click.option('-ms', '--model-source', 'model_sources', type=str, multiple=True,
              help='Peripheral(s) whose trace is the primary source for the model.')
@click.option('-m', '--model-spec', 'model_specs', type=str, multiple=True, metavar='NAME:OUTPUT:PERIPH[,PERIPH]',
              help='Several models, learned separately and corrected together. Repeat per model; replaces '
                   '-p/-o/-mname. Example: -m ADC:adc.c:ADC1,ADC2 -m DMA:dma.c:DMA1,DMAMUX1')
@click.option('--device', 'device_map', type=str, multiple=True, metavar='MODEL=DEVICE',
              help='The configuration\'s device that loads a model (default: the model name in lower case).')
@click.option('--max-rounds', type=int, default=10, show_default=True,
              help='Stop after this many rounds without a match.')
@_run_options
@_encoder_options
@_BUILD_DIR_OPTION
@_llm_options
@_ablation_options('rca')
@click.option('--ms-map', 'ms_map', type=str, multiple=True, metavar='MNAME=PERIPH1,PERIPH2,...',
              help='Per-model source peripherals for --no-rca / --no-verifier with several models.')
@_contract_dir_option
@click.pass_context
def pipeline_command(ctx, hardware_log, config, work_dir, peripherals, output, model_name, model_sources,
                     model_specs, device_map, max_rounds, seconds, stimulus, board, svd, method, n, isr_window,
                     build_dir, model, model_provider, env_file, temperature, reasoning_effort, stateless,
                     max_retries, evaluate, ollama_url, ollama_num_ctx, ollama_timeout, no_verifier, no_rca,
                     no_vio, no_encoder, ms_map, contract_dir):
    from .viomapper.ablations import Ablations
    from .viomapper.codegen.synthesize import make_client
    from .viomapper.encoder.encode import resolve_svd
    from .viomapper.pipeline import ModelSpec, firmware_run_step, run_pipeline

    if model_specs:
        if peripherals or output or model_name or model_sources:
            raise click.UsageError("-m/--model-spec replaces -p, -o, -mname and -ms; use one form.")
        models = []
        for spec in model_specs:
            parts = spec.split(':')
            if len(parts) != 3 or not all(parts):
                raise click.BadParameter(f"'{spec}' must be NAME:OUTPUT:PERIPH[,PERIPH]", param_hint='--model-spec')
            name, out, periphs = parts
            models.append(ModelSpec(name, str(Path(out).resolve()), [p for p in periphs.split(',') if p]))
    else:
        if not peripherals or not output:
            raise click.UsageError("give the model with -p and -o (or several with -m).")
        if len(peripherals) > 1 and not model_name:
            raise click.UsageError("a model learned from several peripherals needs -mname.")
        models = [ModelSpec(model_name or peripherals[0], output, list(peripherals), list(model_sources))]

    sources = {}
    for name, csv in _parse_pairs(ms_map, '=', '--ms-map', 'MNAME=PERIPH1,PERIPH2,...', 'ADC=ADC1,ADC2').items():
        sources[name] = [s.strip() for s in csv.split(',') if s.strip()]
    devices = _parse_pairs(device_map, '=', '--device', 'MODEL=DEVICE', 'USART2=usart2')
    svd_choice = resolve_svd(board, svd)
    settings = _llm_settings(ctx, model, model_provider, env_file, temperature, reasoning_effort, stateless,
                             ollama_url, ollama_num_ctx, ollama_timeout)
    result = run_pipeline(
        hardware_log, work_dir,
        models=models,
        svd=svd_choice,
        run=firmware_run_step(config, seconds=seconds, stimulus=stimulus, devices=devices, svd=svd_choice.path),
        client=make_client(settings),
        settings=settings,
        contract=_load_contract(contract_dir),
        model_sources_map=sources,
        ablations=Ablations(no_encoder=no_encoder, no_rca=no_rca, no_vio=no_vio, no_verifier=no_verifier),
        compile=True,
        build_dir=build_dir,
        max_retries=max_retries,
        max_rounds=max_rounds,
        evaluate=evaluate,
        method=method, n=n, isr_window=isr_window,
    )
    rounds = len(result.rounds)
    if not result.match:
        log.warning("No match after %d round(s); see %s/pipeline.json.", rounds, work_dir)
        sys.exit(1)
    log.info("Matched in round %d; models: %s", rounds, ", ".join(m.output for m in models))


def _add_fastdyn_commands():
    """Running firmware and building models are FastDyn's own commands."""
    from fastdyn import main as fastdyn_main

    cli.add_command(fastdyn_main.run, "run")
    cli.add_command(fastdyn_main.build_model, "build-models")


_add_fastdyn_commands()
