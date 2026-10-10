"""The ``boardrunner`` command."""

import logging
import os
import shutil
import sys
from pathlib import Path

import click

from fastdyn import logs, paths
from fastdyn.utils import parse_config as parse_helper

from . import __version__

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


@click.group()
@click.version_option(prog_name="BoardRunner", version=__version__)
@click.option('-v', '--verbose', is_flag=True, help='Show debug messages.')
@click.option('-q', '--quiet', is_flag=True, help='Show only warnings and errors.')
@click.option('--log-level', 'log_levels', multiple=True, metavar='[LOGGER=]LEVEL',
              help='Set the log level, or one logger\'s level (e.g. boardrunner.viomapper=DEBUG). Repeatable. '
                   'The default comes from FASTDYN_LOG_LEVEL, else INFO.')
@click.option('--log-file', type=click.Path(dir_okay=False, writable=True), default=None,
              help='Also write every log message (DEBUG and above) to this file.')
def cli(verbose, quiet, log_levels, log_file):
    default, overrides = _log_settings(verbose, quiet, log_levels)
    logs.configure(level=default, levels=overrides, log_file=log_file, namespaces=("boardrunner", "fastdyn"))


_contract_dir_option = click.option(
    '--contract-dir',
    type=click.Path(file_okay=False, exists=True, resolve_path=True),
    default=None,
    metavar='PATH',
    help='LibVIO model contract directory (rules, API reference, host functions) for the prompts. '
         'Default: $VIO_CONTRACT_DIR, else `pkg-config --variable=contractdir vio`.'
)


def _load_contract(contract_dir):
    from .viomapper.codegen.prompts.contract import ContractError, load_contract
    try:
        contract = load_contract(contract_dir)
    except ContractError as e:
        raise click.ClickException(str(e)) from e
    log.info("Using the LibVIO model contract %s from %s", contract.version, contract.directory)
    return contract


@cli.command(
    'generate',
    help='Generates the LLM Prompt using the hardware log passed by the user. '
         '[Disclaimer: Use this when generating a model for the first time]'
)
@click.option(
    '-hw', '--hardware-log',
    required=False,
    type=click.Path(resolve_path=True, exists=True),
    help='Path to the log file generated when running the firmware on hardware.',
    metavar='PATH'
)
@click.option(
    '-sm', '--slave-model',
    is_flag=True,
    help='Generate a slave model instead of the main model.'
)
@click.option(
    '-rm', '--reference-model',
    type=click.Path(resolve_path=True, exists=True),
    help='Path to the reference model file.',
    metavar='PATH'
)
@click.option(
    '-fc', '--firmware-code',
    type=click.Path(resolve_path=True, exists=True),
    help='Path to the firmware source code for slave model.',
    metavar='PATH'
)
@click.option(
    '-b', '--board',
    type=str,
    required=True,
    help='Name of the platform on which the firmware is running.'
)
@click.option(
    '-p', '--peripheral',
    type=str,
    multiple=True,
    required=True,
    help='Name of the peripheral targeted for verification.'
)
@click.option(
    '-mname', '--model-name',
    type=str,
    required=False,
    help='Name of the generated model you want to pass to LLM.'
)
@click.option(
    '--method',
    default='ngram',
    show_default=True,
    type=click.Choice(['ngram', 'window', 'other'], case_sensitive=False),
    help='Context minimization method.'
)
@click.option(
    '--n',
    type=int,
    default=2,
    show_default=True,
    help='Value of n for n-gram method.'
)
@click.option(
    '--isr-window',
    type=int,
    default=10000000,
    show_default=True,
    help='ISR window size.'
)
@click.option(
    '-o', '--work-dir',
    default="./fastdyn_work",
    show_default=True,
    metavar='PATH',
    type=click.Path(resolve_path=True, writable=True),
    help='Path to the work directory.'
)
@click.option(
    '-s', '--svd',
    type=click.Path(resolve_path=True, exists=True),
    default=None,
    metavar='PATH',
    help='Optional path to an SVD file or directory.'
)
@click.option(
    '-ms', '--model-source',
    'model_sources',
    type=str,
    multiple=True,
    required=False,
    help='Peripheral(s) whose trace data is the primary source for the target model. '
         'Required when --model-name does not match or contain any peripheral name. '
         'Example: -ms DMA1 -ms DMAMUX1'
)
@click.option(
    '--no-vio',
    is_flag=True,
    default=False,
    help='Ablation mode: strip the LibVIO APIs and the LibVIO-only model rules from the generated '
         'prompt, leaving only the emulator\'s host functions (raw MMIO callbacks).'
)
@click.option(
    '--no-encoder',
    is_flag=True,
    default=False,
    help='Ablation mode: skip the Encoder (context minimizer). Feed the raw I/O trace '
         'directly to the LLM prompt instead of the compact automaton.'
)
@_contract_dir_option
def generate(hardware_log, slave_model, reference_model, firmware_code, board, peripheral, model_name,
             method, n, isr_window, work_dir, svd, model_sources, no_vio, no_encoder, contract_dir):
    """Generates the LLM Prompt using the hardware log passed by the user."""
    # Feature-only imports: keeping them here means core commands such as
    # `fastdyn run` do not need these modules or their dependencies (scipy).
    from .viomapper.encoder import context_minimizer as cm
    from .viomapper.codegen.prompts import prompt_gen as pg
    contract = _load_contract(contract_dir)
    if slave_model:
        if reference_model is None:
            raise click.UsageError("--slave-model requires --reference-model.")
        if firmware_code is None:
            raise click.UsageError("--slave-model requires --firmware-code.")

        if work_dir is not None:
            if not os.path.isdir(work_dir):
                log.warning(f"The output directory: {work_dir} passed by the user does not exist.")
        else:
            work_dir = "fastdyn_work"

        #generate the prompt
        peripheral_str = ", ".join(peripheral)
        slave_type = "spi" if any("spi" in p.lower() for p in peripheral) else "i2c"
        pg_path = pg.slave_model_gen(
            peripheral_name=peripheral_str,
            platform_name=board,
            out_dir=work_dir,
            slave_firmware_path=firmware_code,
            reference_model_path=reference_model,
            slave_type=slave_type,
            contract=contract,
        )

    else:
        if hardware_log is None:
            raise click.UsageError("Generating the model required --hardware-log is required.")

        if work_dir is not None:
            if not os.path.isdir(work_dir):
                log.warning(f"The output directory: {work_dir} passed by the user does not exist.")
        else:
            work_dir = "fastdyn_work"

        if os.path.exists(work_dir):
            log.info(f"The output directory already exists at Path {os.path.abspath(work_dir)}. Deleting it!")
            shutil.rmtree(work_dir)

        log.info(f"Creating output directory at path: {os.path.abspath(work_dir)}")

        os.makedirs(work_dir)

        #discover svd
        svd_input = svd if svd is not None else paths.default_svd_dir()
        platform = (board or "").strip()
        if not platform and (svd is None):
            raise click.UsageError(
                f"Machine platform is required when CMSIS SVD file path is not explicitly given. "
                "Pass --board explicitly."
            )

        if not platform and (svd_input and os.path.isdir(os.path.expanduser(svd_input))):
            raise click.UsageError(
                f"Machine platform is required when CMSIS SVD path points to a directory. "
                "Pass --svd <file> explicitly"
                "OR just Pass --board explicitly."
            )

        try:
            svd_file, svd_key = parse_helper.resolve_svd(
                platform_or_board=platform or "unused",
                svd=svd_input,          # user explicitly passed it here
                default_dir=None,       # no default in this path
                auto_discover=False,    # don’t do repo search when user already gave a path
            )
        except parse_helper.SvdResolutionError as e:
            raise click.ClickException(str(e)) from e

        log.info(f"Using SVD: {svd_file} (key='{svd_key}')")
        svd_device = parse_helper.get_svd_device(svd_file)

        if no_encoder:
            # Ablation A1: Skip the Encoder entirely. Generate prompt from raw I/O trace.
            log.info("Ablation mode: --no-encoder enabled. Skipping Encoder, using raw I/O trace.")
            from .viomapper.codegen.prompts.prompt_gen import generate_prompt_no_encoder
            final_prompt = generate_prompt_no_encoder(
                hardware_log=hardware_log,
                peripheral_name=peripheral[0],
                platform_name=platform,
                no_vio=no_vio,
                model_name=model_name,
                model_sources=model_sources,
                contract=contract,
            )
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            output_path = Path(work_dir) / "initial_prompt.txt"
            output_path.write_text(final_prompt + "\n", encoding="utf-8")
            log.info(f"Ablation prompt (no encoder) written to {output_path}")
        else:
            #minimize the context -- since all the other peripherals are also part of the model, we dont need to do it multiple times
            cm_path = cm.minimize_context(
                out_dir=work_dir,
                log_file=hardware_log,
                platform=platform,
                method=method,
                peripheral=peripheral[0],
                n=n,
                svd_device=svd_device,
                isr_window=isr_window,
                cm_dir_name="out_cm"
                )

            #generate the prompt - we will generate a prompt such that it covers all the peripherals requested by the user
            #TODO: Refactor and clean later
            if len(peripheral) > 1:
                for periph in peripheral:
                    periph_path = os.path.join(cm_path, periph)
                    if not os.path.exists(periph_path):
                        log.error(f"Requested Peripheral {periph} does not exist!")
                        sys.exit(1)

                # Validate model_sources if explicitly provided
                if model_sources:
                    for ms in model_sources:
                        if ms not in peripheral:
                            log.error(
                                f"--model-source '{ms}' is not in the peripheral list {list(peripheral)}. "
                                f"Only peripherals passed with -p can be used as a model source."
                            )
                            sys.exit(1)

                pg_path = pg.initial_prompt_gen_multiple_periphs(
                    analysis_dir=cm_path,
                    model_name=model_name,
                    peripherals=peripheral,
                    model_sources=model_sources or None,   # pass None so the function applies its heuristic
                    out_dir=work_dir,
                    no_vio=no_vio,
                    user_obs='',
                    contract=contract,
                )
            else:
                pg_path = pg.initial_prompt_gen(
                    analysis_dir=cm_path,
                    peripheral=peripheral[0],
                    out_dir=work_dir,
                    no_vio=no_vio,
                    contract=contract,
                )


@cli.command(
    'verifier',
    help=(
        'Verifies the model passed by the user for a given peripheral. '
        'Generates a prompt in case of failure. '
        '[Disclaimer: Use this when iterating a generated model for correction]'
    )
)
@click.option(
    '-hw', '--hardware-log',
    required=True,
    type=click.Path(resolve_path=True, exists=True),
    help='Path to the log file generated when running the firmware on hardware.',
    metavar='PATH'
)
@click.option(
    '-em', '--emulation-log',
    required=True,
    type=click.Path(resolve_path=True, exists=True),
    help='Path to the log file generated when running the firmware on the elder model using emulation.',
    metavar='PATH'
)
@click.option(
    '-d', '--device-model',
    'device_models',
    type=str,
    multiple=True,
    required=True,
    help='Model name and path as NAME:PATH. '
         'Example: -d ADC1:model.c -d DMA_with_DMAMUX1:model2.c'
)
@click.option(
    '-b', '--board',
    type=str,
    required=True,
    help='Name of the platform on which the firmware is running.'
)
@click.option(
    '-p', '--peripheral',
    type=str,
    multiple=True,
    required=True,
    help='Name of the peripheral targeted for verification.'
)
@click.option(
    '-mname', '--model-name',
    'model_names',
    type=str,
    multiple=True,
    required=True,
    help='Name(s) of the model(s) being verified.'
)
@click.option(
    '--method',
    default='ngram',
    show_default=True,
    type=click.Choice(['ngram', 'window', 'other'], case_sensitive=False),
    help='Context minimization method.'
)
@click.option(
    '--n',
    type=int,
    default=2,
    show_default=True,
    help='Value of n for n-gram method.'
)
@click.option(
    '--isr-window',
    type=int,
    default=10000000,
    show_default=True,
    help='ISR window size.'
)
@click.option(
    '-o', '--work-dir',
    default="./fastdyn_work",
    show_default=True,
    metavar='PATH',
    type=click.Path(resolve_path=True, writable=True),
    help='Path to the work directory.'
)
@click.option(
    '-s', '--svd',
    type=click.Path(resolve_path=True, exists=True),
    default=None,
    metavar='PATH',
    help='Optional path to an SVD file or directory.'
)
@click.option(
    '--no-rca',
    is_flag=True,
    default=False,
    help='Ablation mode: on mismatch, generate a generic retry prompt instead of '
         'the targeted RCA-based revised_prompt.txt.'
)
@click.option(
    '--no-encoder',
    is_flag=True,
    default=False,
    help='Ablation mode: on mismatch, generate a correction prompt using raw I/O '
         'trace data instead of the Encoder\'s structured analysis.'
)
@click.option(
    '--no-vio',
    is_flag=True,
    default=False,
    help='Ablation mode: strip the LibVIO APIs and the LibVIO-only model rules from the correction prompt.'
)
@click.option(
    '--no-verifier',
    is_flag=True,
    default=False,
    help='Ablation mode: on mismatch, provide only the encoded hardware trace and '
         'the broken model source code. No emulation trace feedback — the LLM must '
         'self-diagnose by comparing its code against the hardware evidence.'
)
@click.option(
    '--ms-map',
    'ms_map',
    type=str,
    multiple=True,
    metavar='MNAME=PERIPH1,PERIPH2,...',
    help='Per-model source-peripheral mapping. Required for --no-rca and '
         '--no-verifier in compositional (multi --mname) mode so each model '
         'is corrected in isolation. Repeat once per --mname. '
         'Example: --ms-map "ADC=ADC1,ADC2,ADC12_Common" --ms-map "DMA_with_DMAMUX1=DMA1,DMAMUX1"'
)
@_contract_dir_option
def verifier(hardware_log, emulation_log, device_models, model_names, board,
             peripheral, method, n, isr_window, work_dir, svd,
             no_rca, no_encoder, no_vio, no_verifier, ms_map, contract_dir):
    """Verifies the model against hardware and emulation logs."""
    # Feature-only imports: keeping them here means core commands such as
    # `fastdyn run` do not need these modules or their dependencies (scipy).
    from .viomapper.encoder import context_minimizer as cm
    from .viomapper.codegen.prompts import prompt_gen as pg
    from .viomapper.verifier import verifier as verify
    contract = _load_contract(contract_dir)
    log.info("Running Verifier")

    # ── Work directory setup ─────────────────────────────────────────────────
    if work_dir is not None:
        if not os.path.isdir(work_dir):
            log.warning(f"The output directory: {work_dir} passed by the user does not exist.")
    else:
        work_dir = "fastdyn_work"

    if os.path.exists(work_dir):
        log.info(f"The output directory already exists at Path {os.path.abspath(work_dir)}. Deleting it!")
        shutil.rmtree(work_dir)

    log.info(f"Creating output directory at path: {os.path.abspath(work_dir)}")
    os.makedirs(work_dir)

    # ── Parse --ms-map MNAME=PERIPH1,PERIPH2,... entries into a dict ─────────
    model_sources_map = {}
    for entry in ms_map:
        if '=' not in entry:
            log.error(
                f"--ms-map '{entry}' must be in MNAME=PERIPH1,PERIPH2,... format.\n"
                f"Example: --ms-map \"ADC=ADC1,ADC2,ADC12_Common\""
            )
            sys.exit(1)
        mname, sources_csv = entry.split('=', 1)
        mname = mname.strip()
        sources = [s.strip() for s in sources_csv.split(',') if s.strip()]
        if not sources:
            log.error(f"--ms-map entry for '{mname}' has no peripherals listed.")
            sys.exit(1)
        model_sources_map[mname] = sources

    # ── Parse and validate NAME:PATH device model entries ───────────────────
    model_to_path = {}
    for entry in device_models:
        if ':' not in entry:
            log.error(
                f"--device-model '{entry}' must be in NAME:PATH format.\n"
                f"Example: -d ADC1:boardrunner/model.c"
            )
            sys.exit(1)
        name, path = entry.split(':', 1)
        name, path = name.strip(), path.strip()
        if not os.path.exists(path):
            log.error(f"Model file for '{name}' not found: {path}")
            sys.exit(1)
        model_to_path[name] = path

    for mname in model_names:
        if mname not in model_to_path:
            log.error(
                f"No -d entry found for model '{mname}'.\n"
                f"Add: -d {mname}:/path/to/model.c"
            )
            sys.exit(1)

    # ── SVD discovery ────────────────────────────────────────────────────────
    svd_input = svd if svd is not None else paths.default_svd_dir()
    platform = (board or "").strip()

    if not platform and (svd is None):
        raise click.UsageError(
            "Machine platform is required when CMSIS SVD file path is not explicitly given. "
            "Pass --board explicitly."
        )

    if not platform and (svd_input and os.path.isdir(os.path.expanduser(svd_input))):
        raise click.UsageError(
            "Machine platform is required when CMSIS SVD path points to a directory. "
            "Pass --svd <file> explicitly OR just Pass --board explicitly."
        )

    try:
        svd_file, svd_key = parse_helper.resolve_svd(
            platform_or_board=platform or "unused",
            svd=svd_input,
            default_dir=None,
            auto_discover=False,
        )
    except parse_helper.SvdResolutionError as e:
        raise click.ClickException(str(e)) from e

    log.info(f"Using SVD: {svd_file} (key='{svd_key}')")
    svd_device = parse_helper.get_svd_device(svd_file)

    # ── Context minimization — hardware ──────────────────────────────────────
    cm_path_hardware = cm.minimize_context(
        out_dir=work_dir,
        log_file=hardware_log,
        platform=platform,
        method=method,
        peripheral=peripheral[0],
        n=n,
        svd_device=svd_device,
        isr_window=isr_window,
        cm_dir_name="out_cm"
    )

    for periph in peripheral:
        periph_path = os.path.join(cm_path_hardware, periph)
        if not os.path.exists(periph_path):
            log.error(f"Requested peripheral '{periph}' not found in hardware context: {periph_path}")
            sys.exit(1)

    # ── Context minimization — emulation ─────────────────────────────────────
    cm_path_emulation = cm.minimize_context(
        out_dir=work_dir,
        log_file=emulation_log,
        platform=platform,
        method=method,
        peripheral=peripheral[0],
        n=n,
        svd_device=svd_device,
        isr_window=isr_window,
        cm_dir_name="emulation"
    )

    for periph in peripheral:
        periph_path = os.path.join(cm_path_emulation, periph)
        if not os.path.exists(periph_path):
            log.warning(f"Requested peripheral '{periph}' not found in emulation context: {periph_path}. Emulation likely crashed early.")

    # ── Verification and prompt generation ───────────────────────────────────
    if len(peripheral) == 1:
        not_match, diff_obj = verify.verify_automata(
            automata1=cm_path_hardware,
            automata2=cm_path_emulation,
            peripheral=peripheral[0]
        )

        if not_match:
            if no_verifier:
                # Ablation: No Verifier feedback. The LLM receives the original
                # encoder-based prompt (HW trace structured) + the broken model
                # source code + generic "fix it". No emulation trace, no diffs,
                # no runtime feedback at all — the LLM must self-diagnose.
                log.warning("Log mismatch! --no-verifier: generating blind retry prompt.")

                periph_dir = os.path.join(cm_path_hardware, peripheral[0])
                if os.path.isdir(periph_dir):
                    original_prompt = pg.generate_prompt(periph_dir, contract=contract)
                else:
                    original_prompt = ""
                    log.warning("Could not find encoder output for --no-verifier fallback.")

                model_source = ""
                model_path = list(model_to_path.values())[0]
                try:
                    with open(model_path, "r", encoding="utf-8") as mf:
                        model_source = mf.read()
                except Exception as e:
                    log.warning(f"Could not read model source for --no-verifier prompt: {e}")

                generic_prompt = (
                    original_prompt +
                    "\n\n## Current Model (Failed Verification)\n"
                    "The following model was generated but failed verification against the hardware trace.\n"
                    "```c\n" + model_source + "\n```\n\n"
                    "## Correction Required\n"
                    "The model above does not correctly reproduce the hardware behavior shown in the trace data. "
                    "Please analyze the hardware trace and the model source code, identify the bug, "
                    "and generate a corrected model.\n"
                )
                prompt_path = os.path.join(work_dir, "initial_prompt.txt")
                with open(prompt_path, "w", encoding="utf-8") as f:
                    f.write(generic_prompt)
                log.info("No-verifier retry prompt written to %s", prompt_path)
            elif no_rca:
                # Ablation A2: No RCA. The Verifier still runs and produces diffs
                # (HW vs EM encoded traces compared). The LLM sees the Verifier's
                # comparison data + broken model source + generic "fix it", but NOT
                # RCA's targeted diagnostic narrative or SEARCH/REPLACE strategy.
                # Written as initial_prompt.txt so LLM does full model regeneration.
                log.warning("Log mismatch! --no-rca: generating prompt with Verifier diffs but no RCA analysis.")

                pg_path = pg.iteration_prompt_gen(
                    diff_obj=diff_obj,
                    device_model_path=list(model_to_path.values())[0],
                    peripheral=peripheral[0],
                    out_dir=work_dir,
                    no_vio=no_vio,
                    no_rca=True,
                    contract=contract,
                )
            elif no_encoder:
                # Ablation A1 correction: use raw traces instead of structured
                # encoder analysis, but keep the SEARCH/REPLACE correction strategy.
                log.warning("Log mismatch! --no-encoder: generating correction prompt with raw traces.")

                # Build peripheral address ranges from SVD for trace filtering
                peripheral_ranges = []
                for p in svd_device.peripherals:
                    if p.name.upper() == peripheral[0].upper():
                        size = 0x400
                        if hasattr(p, 'address_block') and p.address_block:
                            size = p.address_block.size
                        peripheral_ranges.append((p.base_address, p.base_address + size))

                pg_path = pg.iteration_prompt_gen(
                    diff_obj=diff_obj,
                    device_model_path=list(model_to_path.values())[0],
                    peripheral=peripheral[0],
                    out_dir=work_dir,
                    no_encoder=True,
                    hardware_log=hardware_log,
                    emulation_log=emulation_log,
                    peripheral_ranges=peripheral_ranges,
                    no_vio=no_vio,
                    contract=contract,
                )
            else:
                log.warning("Log mismatch! Generating prompt.")
                pg_path = pg.iteration_prompt_gen(
                    diff_obj=diff_obj,
                    device_model_path=list(model_to_path.values())[0],
                    peripheral=peripheral[0],
                    out_dir=work_dir,
                    no_vio=no_vio,
                    contract=contract,
                )
        else:
            log.info("Both hardware log and emulation log matched!")

    else:
        pg_path = pg.iteration_prompt_gen_multiple_periph(
            cm_path_hardware=cm_path_hardware,
            cm_path_emulation=cm_path_emulation,
            peripherals=peripheral,
            model_names=model_names,
            model_to_path=model_to_path,
            out_dir=work_dir,
            no_encoder=no_encoder,
            no_rca=no_rca,
            no_verifier=no_verifier,
            no_vio=no_vio,
            hardware_log=hardware_log,
            emulation_log=emulation_log,
            model_sources_map=model_sources_map or None,
            contract=contract,
        )


@cli.command(
    'llm',
    help=(
        'Sends a prompt from a work directory to an LLM provider and processes '
        'the response. For initial_prompt.txt: extracts C code and writes the model. '
        'For revised_prompt.txt: parses SEARCH/REPLACE blocks and patches the model.'
    )
)
@click.option(
    '-d', '--work-dir',
    required=True,
    type=click.Path(resolve_path=True, exists=True),
    help='Path to the FastDyn work directory containing initial_prompt.txt or revised_prompt.txt.',
    metavar='PATH'
)
@click.option(
    '-o', '--output',
    required=True,
    multiple=True,
    type=click.Path(resolve_path=True),
    help='Path to the model .c file(s). Can be specified multiple times.',
    metavar='PATH'
)
@click.option(
    '--model',
    default='gpt-4o',
    show_default=True,
    type=str,
    help='Model name to use.'
)
@click.option(
    '--model-provider',
    default='openai',
    show_default=True,
    type=click.Choice(['openai', 'ollama'], case_sensitive=False),
    help='LLM provider backend.'
)
@click.option(
    '--env-file',
    default='~/.fastdyn.env',
    show_default=True,
    type=str,
    help='Path to .env file containing OPENAI_API_KEY.'
)
@click.option(
    '--temperature',
    default=0.2,
    show_default=True,
    type=float,
    help='Sampling temperature. For Ollama, the default is 0.1 unless this option is explicitly set.'
)
@click.option(
    "--reasoning-effort",
    type=click.Choice(["none", "minimal", "low", "medium", "high", "xhigh"]),
    default=None,
    help="Reasoning effort for supported gpt-5 and o-series models."
)
@click.option(
    '--stateless/--no-stateless',
    default=True,
    show_default=True,
    help='Keep (--stateless) or strip (--no-stateless) the conversation reset line in prompts.'
)
@click.option(
    '--compile/--no-compile',
    default=False,
    show_default=True,
    help='Compile the model(s) after writing/patching, with FastDyn\'s model builder.'
)
@click.option(
    '--build-dir',
    default='build/models',
    show_default=True,
    type=click.Path(resolve_path=True, file_okay=False),
    help='Where --compile puts the built models (<name>.so for each <name>.c).',
    metavar='PATH'
)
@click.option(
    '--max-retries',
    default=1,
    show_default=True,
    type=int,
    help='Maximum number of retry attempts on patch or compilation failure.'
)
@click.option(
    '--evaluate/--no-evaluate',
    default=False,
    show_default=True,
    help='Enable evaluation metrics logging. Writes per-call metrics to fastdyn_llm_history/metrics.jsonl.'
)
@click.option(
    '--ollama-url',
    default='http://127.0.0.1:11434',
    show_default=True,
    type=str,
    help='Base URL for the Ollama HTTP server. Use SSH port forwarding for remote servers.'
)
@click.option(
    '--ollama-num-ctx',
    default=262144,
    show_default=True,
    type=int,
    help='Ollama num_ctx option. Set to 0 to use the server/model default.'
)
@click.option(
    '--ollama-timeout',
    default=1800.0,
    show_default=True,
    type=float,
    help='Timeout in seconds for non-streaming Ollama requests.'
)
@click.pass_context
def llm(ctx, work_dir, output, model, model_provider, env_file, temperature,
        reasoning_effort, stateless, compile, build_dir, max_retries, evaluate,
        ollama_url, ollama_num_ctx, ollama_timeout):
    """Sends a prompt to the selected LLM provider and processes the response."""
    # Feature-only imports, kept here so core commands do not depend on the llm package.
    from .viomapper.codegen.llm.handlers import llm_history_next
    from .viomapper.codegen.llm.llm_client import LLMClient, LLMClientError, load_api_key
    from .viomapper.codegen.parse import (
        extract_c_code, parse_search_replace_blocks, ParsingError
    )
    from .viomapper.codegen.patch import (
        apply_search_replace_patches, write_patched_file, write_model_file, PatchError
    )

    # -- Determine prompt type ------------------------------------------------
    initial_prompt_path = os.path.join(work_dir, "initial_prompt.txt")
    revised_prompt_path = os.path.join(work_dir, "revised_prompt.txt")

    if os.path.isfile(revised_prompt_path):
        prompt_path = revised_prompt_path
        prompt_type = "revised"
        log.info("Found revised_prompt.txt -- using SEARCH/REPLACE patch mode")
    elif os.path.isfile(initial_prompt_path):
        prompt_path = initial_prompt_path
        prompt_type = "initial"
        log.info("Found initial_prompt.txt -- using full code extraction mode")
    else:
        log.error(
            "No prompt file found in %s. "
            "Expected initial_prompt.txt or revised_prompt.txt.", work_dir
        )
        sys.exit(1)

    # -- Read prompt ----------------------------------------------------------
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    if not prompt_text.strip():
        log.error("Prompt file is empty: %s", prompt_path)
        sys.exit(1)

    log.info("Read prompt from %s (%d characters)", prompt_path, len(prompt_text))

    # -- Persistent LLM history -----------------------------------------------
    # Saved in fastdyn_llm_history/ next to the work directory, never deleted.
    # Each invocation gets a new NNN prefix; retries within the same run get
    # separate response files (NNN_response_1.txt, NNN_response_2.txt, ...).
    history_dir = os.path.join(os.path.dirname(work_dir), "fastdyn_llm_history")
    history_iter = llm_history_next(history_dir)
    history_prefix = os.path.join(history_dir, f"{history_iter:03d}")
    with open(f"{history_prefix}_prompt.txt", "w", encoding="utf-8") as f:
        f.write(prompt_text)
    log.info("LLM history prompt saved to %s_prompt.txt (iteration %d)", history_prefix, history_iter)

    # -- Validate output file for revised prompts ----------------------------
    if prompt_type == "revised":
        for out_path in output:
            if not os.path.isfile(out_path):
                log.error(
                    "Revised prompt mode requires an existing model file to patch. "
                    "File not found: %s", out_path
                )
                sys.exit(1)

    model_provider = model_provider.lower()

    # -- Initialize LLM client ------------------------------------------------
    try:
        if model_provider == "ollama":
            from .viomapper.codegen.llm.ollama_client import OllamaClient

            if reasoning_effort and reasoning_effort != "none":
                log.warning(
                    "--reasoning-effort is ignored for --model-provider ollama. "
                    "Use Ollama model configuration for reasoning controls."
                )

            temperature_source = None
            if hasattr(ctx, "get_parameter_source"):
                temperature_source = ctx.get_parameter_source("temperature")
            ollama_temperature = 0.1 if str(temperature_source).endswith("DEFAULT") else temperature

            client = OllamaClient(
                model=model,
                base_url=ollama_url,
                temperature=ollama_temperature,
                num_ctx=ollama_num_ctx or None,
                timeout=ollama_timeout,
            )
        else:
            api_key = load_api_key(env_file)
            client = LLMClient(
                api_key=api_key,
                model=model,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            )
    except LLMClientError as e:
        log.error(str(e))
        sys.exit(1)

    # -- Evaluation metrics setup -----------------------------------------------
    metrics_path = None
    if evaluate:
        import json as _json
        metrics_path = os.path.join(history_dir, "metrics.jsonl")
        log.info("Evaluation mode enabled. Metrics will be written to %s", metrics_path)

    def _write_metrics(metrics, attempt_num, call_type, extra=None):
        """Append a metrics JSON line if --evaluate is enabled."""
        if not evaluate or metrics is None:
            return
        entry = metrics.to_dict()
        entry["iteration"] = history_iter
        entry["attempt"] = attempt_num
        entry["type"] = call_type
        entry["model_provider"] = model_provider
        entry["reasoning_effort"] = reasoning_effort
        if extra:
            entry.update(extra)
        with open(metrics_path, "a", encoding="utf-8") as mf:
            mf.write(_json.dumps(entry) + "\n")

    # -- Send prompt and process response -------------------------------------
    attempt = 0
    max_attempts = 1 + max_retries
    previous_response = None

    while attempt < max_attempts:
        attempt += 1
        is_retry = attempt > 1

        try:
            if is_retry and previous_response:
                log.info("Retry attempt %d/%d...", attempt - 1, max_retries)
                response_text, call_metrics = client.send_followup_prompt(
                    original_prompt=prompt_text,
                    previous_response=previous_response,
                    error_context=error_context,
                    stateless=stateless,
                )
            else:
                response_text, call_metrics = client.send_prompt(prompt_text, stateless=stateless)
        except LLMClientError as e:
            log.error("LLM request failed: %s", str(e))
            sys.exit(1)

        # Save raw response for debugging/auditing
        response_path = os.path.join(work_dir, "llm_response.txt")
        with open(response_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        log.info("Raw LLM response saved to %s", response_path)

        # Persist to history (one file per attempt so retries are all kept)
        history_response_path = f"{history_prefix}_response_{attempt}.txt"
        with open(history_response_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        log.info("LLM history response saved to %s", history_response_path)

        previous_response = response_text

        # -- Process based on prompt type -------------------------------------
        success = False
        error_context = ""

        from .viomapper.codegen.llm.handlers import (
            handle_initial_prompt,
            handle_revised_prompt,
            handle_compilation,
        )

        if prompt_type == "initial":
            success, error_context = handle_initial_prompt(
                response_text, output[0], work_dir
            )
        else:
            success, error_context = handle_revised_prompt(
                response_text, output, work_dir
            )

        if not success:
            call_type = "followup" if is_retry else ("revision" if prompt_type == "revised" else "initial")
            _write_metrics(call_metrics, attempt, call_type, {"result": "parse_fail"})
            if attempt < max_attempts:
                # Use builtin input() to avoid click.confirm TTY hangs
                user_reply = input("Send a follow-up request to the LLM with error context? [Y/n]: ").strip().lower()
                retry = (user_reply == "y" or user_reply == "")

                if not retry:
                    log.info("User chose not to retry. Exiting.")
                    sys.exit(1)
                continue
            else:
                log.error("All %d attempt(s) exhausted. Exiting.", max_attempts)
                sys.exit(1)

        # -- Optional compilation step ----------------------------------------
        if compile:
            compile_success, compile_error, is_setup_error = handle_compilation(output, build_dir)
            if not compile_success:
                call_type = "followup" if is_retry else ("revision" if prompt_type == "revised" else "initial")
                _write_metrics(call_metrics, attempt, call_type, {"result": "compile_fail"})
                if is_setup_error:
                    log.error("Aborting LLM loop due to compilation setup error.")
                    sys.exit(1)

                error_context = compile_error
                if attempt < max_attempts:
                    # Use builtin input() to avoid click.confirm TTY hangs
                    user_reply = input("Compilation failed. Send a follow-up request to the LLM? [Y/n]: ").strip().lower()
                    retry = (user_reply == "y" or user_reply == "")

                    if not retry:
                        log.info("User chose not to retry. Exiting.")
                        sys.exit(1)
                    continue
                else:
                    log.error("All %d attempt(s) exhausted. Exiting.", max_attempts)
                    sys.exit(1)

        # If we reach here, everything succeeded
        call_type = "followup" if is_retry else ("revision" if prompt_type == "revised" else "initial")
        _write_metrics(call_metrics, attempt, call_type, {"result": "success"})
        log.info("LLM processing completed successfully.")
        break


def _add_fastdyn_commands():
    """Running firmware and building models are FastDyn's own commands."""
    from fastdyn import main as fastdyn_main

    cli.add_command(fastdyn_main.run, "run")
    cli.add_command(fastdyn_main.build_model, "build-models")


_add_fastdyn_commands()
