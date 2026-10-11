"""RCA: revision prompts from the Verifier's diffs (paper Fig. 7).

A revision prompt shows the LLM where the emulated model diverged from the
hardware and asks for SEARCH/REPLACE corrections (or, in the --no-rca and
--no-verifier ablations, for a full regeneration). The rules, APIs and model
shape come from the same place as CodeGen's initial prompts.
"""

import logging
import os
import textwrap
from pathlib import Path

from boardrunner.viomapper.verifier import verifier as verify
from boardrunner.viomapper.encoder.summary import parse_summary_file
from boardrunner.viomapper.codegen.prompts.prompt_gen import (
    _contract,
    _includes_note,
    _model_sketch,
    _render_apis_and_rules,
    context_peripheral_instructions,
)

log = logging.getLogger(__name__)


slave_bug_blocker = """\
### Slave Device Bug Detection (HARD BLOCKER)
If your analysis of the trace mismatches indicates that the root cause is NOT in \
this model but in an attached slave device (e.g., an I2C/SPI slave returning \
wrong data, not ACK-ing correctly, or mishandling a protocol sequence):
1. Do NOT generate SEARCH/REPLACE corrections for the master model — applying \
   patches to the wrong model will introduce new bugs and complicate debugging.
2. State clearly which slave device you suspect and why (cite specific trace \
   evidence: register values, entropy mismatches, protocol violations).
3. Ask the user to provide the slave model source code so you can examine and \
   correct it alongside the master model.

The slave model will have the following callback interface that MUST NOT be changed:
- For I2C slaves: `vio_i2c_slave_init`, `vio_i2c_slave_event`, `vio_i2c_slave_send`, `vio_i2c_slave_recv`
- For SPI slaves: `vio_spi_slave_init`, `vio_spi_slave_set_cs`, `vio_spi_slave_transfer`
"""


search_replace_prompting = """
### 3.Output your code changes using SEARCH/REPLACE blocks.
Instead of providing the full source code, provide your code changes using SEARCH/REPLACE blocks to update the model/s file.
Rules for SEARCH/REPLACE blocks:
1. The code in the SEARCH section must exactly match the current file, character for character, including all whitespace and indentation.
2. Include enough lines in the SEARCH block to uniquely identify the location (usually 3-5 lines of context around the change).
3. Do not use abbreviations, placeholders, or comments like `// ... rest of function` in the SEARCH block.
4. Output multiple blocks if you need to make changes in different parts of the file.
5. Wrap each SEARCH/REPLACE block in a standard text markdown block (text ... ) so it can be easily parsed.
6. **NEVER leave the REPLACE section empty.** The parser requires at least one line of content between `=======` and `>>>>>>> REPLACE`. To delete a block of code entirely, replace it with a single comment line, for example `/* removed */`. Do NOT produce an empty REPLACE section — this will cause a parse error.
Use this exact format:
// FILE: target_filename.c
<<<<<<< SEARCH
[exact old code to find]
=======
[new code to replace it with — must never be empty; use /* removed */ to delete]
>>>>>>> REPLACE
"""


# ── LLM-facing instructions for verifier diff interpretation ────────────────
# These are added to prompts by prompt_gen.py, NOT by verifier.py.
# Verifier reports raw facts; these constants add interpretation for the LLM.
polling_interpretation_instructions = """
NOTE: Polling patterns indicate that the polled register has bits that hardware
auto-clears or auto-sets.

CRITICAL WARNING: Just because a Polling detection appears in the "emulated model"
list DOES NOT mean the emulation is handling it correctly! If the emulation gets
stuck in an INFINITE POLLING LOOP forever, the verifier will still detect the
polling pattern because it sees the infinite reads.
Therefore, if you see a Polling Loop on a register (e.g. Polling Loop on REG_B), you
MUST check the "Entropy Mismatch Details" for the polled register (e.g. REG_B).
If the polled register has LOW (0.00) entropy in emulation while having >0 entropy
in hardware, it means your model is HANGING in an infinite loop and you MUST
implement self-clearing/auto-transitioning bits in that register!
"""


def _build_analysis_section(diff_obj, state_data_with_instructions, no_encoder, hardware_log, emulation_log, peripheral_name, peripheral_ranges):
    """Build the analysis data section for the correction prompt.

    When no_encoder is False (default), returns the structured encoder analysis
    (init, loops, entropy, rare transitions, state, ISR).

    When no_encoder is True (A1 ablation), returns the raw hardware I/O trace
    filtered to the target peripheral's address range.
    """
    if no_encoder and hardware_log:
        # A1 ablation: full raw traces without any filtering or SVD-based
        # address resolution. The LLM must identify the target peripheral's
        # registers on its own — using SVD to filter would leak Encoder
        # knowledge. Both hardware and emulation traces are included so the
        # LLM can compare them directly.
        # We only strip internal emulator bookkeeping lines (SysTick IRQ
        # taken/served) that are not MMIO accesses and carry no register info.
        def _read_trace_strip_irq_noise(log_path):
            lines = []
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.rstrip()
                    if 'Vector = 0x0000000F' in stripped:
                        continue
                    lines.append(stripped)
            return '\n'.join(lines)

        raw_hw_trace = _read_trace_strip_irq_noise(hardware_log)
        hw_line_count = raw_hw_trace.count('\n') + 1

        em_section = ""
        if emulation_log:
            raw_em_trace = _read_trace_strip_irq_noise(emulation_log)
            em_lines = raw_em_trace.split('\n')
            # Cap emulation trace to 2x hardware trace length to prevent
            # infinite-loop models from blowing up the prompt. This is not
            # Encoder-derived filtering — just a mechanical size cap based
            # on the expected execution length.
            if len(em_lines) > hw_line_count * 2:
                truncated_count = len(em_lines)
                em_lines = em_lines[:hw_line_count * 2]
                raw_em_trace = '\n'.join(em_lines)
                raw_em_trace += f"\n\n[TRUNCATED: emulation trace had {truncated_count} lines, capped at {hw_line_count * 2} (2x hardware trace). The model likely contains an infinite polling loop.]"

            em_section = f"""

## Raw Emulated Model I/O Trace
The following is the emulated model's full trace. Compare this against the
hardware trace above to identify where the model's behavior diverges.
```
{raw_em_trace}
```"""

        return f"""## Raw Hardware I/O Trace
The following is the complete raw hardware trace. Use this to identify
register behavior, value transitions, and expected read/write patterns for {peripheral_name}.
```
{raw_hw_trace}
```{em_section}"""

    # Default: structured encoder analysis
    return f"""## Initialization Sequence (`init.txt`):
This file contains all accesses that occur before the main runtime loop begins.
```
{diff_obj.diff_init_data}
```

## Detected Runtime Loops (`loop_pattern_*.txt`):
These files contain the most common repeating sequences of operations during runtime.
```
{diff_obj.diff_loop_pattern_data}
```

## Rare Value Transitions (`rare_transitions.txt`):
These are read values from LOW-entropy (status/control) registers that did NOT appear in the dominant loop patterns above. They represent infrequent but important state changes that the model MUST handle correctly. Pay close attention to these values — they reveal how the register behaves in a different operational phase (e.g. data available vs. idle).
```
{diff_obj.rare_transitions_data}
```

## Stateful Behavior Analysis (`state.txt`):
This file identifies programming patterns like Read-Modify-Write (RMW), which indicate stateful registers.
```
{state_data_with_instructions}
```

## Register Entropy Analysis (`entropy.txt`):
This file measures the randomness of values read from registers. High entropy suggests data registers, while low entropy suggests status registers.
```
{diff_obj.diff_entropy_data}
```
## Runtime Data Accesses
This file contains all the accesses information for the data registers
{diff_obj.diff_runtime_trace}

## ISR Analysis (`isr_analysis.txt`)
This file contains information about IRQs.
```
{diff_obj.isr_analysis_data}
```

{diff_obj.svd_bitfields_data}"""


def iteration_prompt_gen(diff_obj, peripheral, out_dir, device_model_path, show_prompt=True, max_model_chars=120000,
                         no_encoder=False, hardware_log=None, emulation_log=None, peripheral_ranges=None, no_vio=False,
                         no_rca=False, contract=None):
    '''
    Based on the difference object, create a correction prompt using SEARCH/REPLACE
    blocks. This is consistent with the multi-peripheral verifier flow.

    When no_encoder=True, the structured analysis sections (init, loop patterns,
    entropy, rare transitions, state) are replaced with the raw hardware I/O trace,
    preserving the SEARCH/REPLACE correction strategy.
    '''
    platform_name = diff_obj.platform_name
    peripheral_name = peripheral
    device_model = ''
    contract = _contract(contract)
    if not show_prompt:
        log.warning(
            "show_prompt=False: model source will be hidden from LLM. "
            "SEARCH/REPLACE corrections will likely fail."
        )
    model_filename = os.path.basename(device_model_path)

    if show_prompt:
        device_model = Path(device_model_path).read_text(encoding="utf-8", errors="replace")
        if max_model_chars and len(device_model) > max_model_chars:
            device_model = device_model[:max_model_chars] + "\n/* ... truncated ... */"

    # Build the state data with LLM-facing instructions appended
    state_data_with_instructions = diff_obj.diff_state_data
    if state_data_with_instructions and not state_data_with_instructions.strip().startswith("[NO DATA"):
        state_data_with_instructions += "\n" + polling_interpretation_instructions

    if no_rca:
        # No RCA ablation: show the Verifier's diffs (HW vs EM comparison)
        # but without RCA's targeted diagnostic narrative or SEARCH/REPLACE
        # strategy. The LLM sees what diverged but must figure out the fix
        # on its own via full model regeneration.
        final_prompt = f'''
Take this prompt independent from previous prompt history.

You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals. You have read the reference manual for {platform_name} with special familiarity with {peripheral_name} peripheral.
Your task is to analyze the following summary of MMIO trace data and generate a complete C device model.

{_render_apis_and_rules(contract, no_vio)}

## Trace Log Schema:
The logs below are formatted as arrays containing the following fields: [Operation, Peripheral, Register, Memory Address, Register Value, Program Counter (PC)]. Pay close attention to the Register Value differences between Hardware and the Emulated Model.

--- START OF ANALYSIS DATA ---

## Platform:
{platform_name}

## Peripheral Name:
{peripheral_name}

{_build_analysis_section(diff_obj, state_data_with_instructions, no_encoder, hardware_log, emulation_log, peripheral_name, peripheral_ranges)}

--- END OF ANALYSIS DATA ---

## Correction Required
A previous model was generated but failed verification. The trace comparison above shows where the hardware and emulated model behaviors diverge. Please generate a corrected complete C device model that faithfully reproduces the observed hardware behavior.

## Required Output Format:

### 1. Previous Model Failure Analysis
A concise, one-paragraph summary explaining the most likely reason for the mismatches.

### 2. Register Analysis
A bulleted list of the important registers mentioned in the traces and their inferred functions.

### 3. C Device Model Source Code
The C source code for MMIO read and write callback for {peripheral_name} emulation and any initialization you need for the emulation only. The code must be fully self-contained and ready to be compiled. {_includes_note(no_vio)}

{_model_sketch(peripheral_name, no_vio)}
'''
    else:
        final_prompt = f'''
Take this prompt independent from previous prompt history.

You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals. You have read the reference manual for {platform_name} with special familiarity with {peripheral_name} peripheral.
Your task is to analyze the following summary of MMIO trace data and correct the existing C device model.

## Backward-pass/Correction
Below is the current device model. The logs show mismatches between hardware and emulation; identify the root cause and fix it.

## Model Under Correction
You may produce SEARCH/REPLACE blocks for this file:
- `{peripheral_name}` -> `{model_filename}`
Each SEARCH/REPLACE block MUST begin with a comment identifying its target file:
`// FILE: {model_filename}`

--- START OF CURRENT MODEL ---

## Model: `{peripheral_name}`  |  File: `{model_filename}`
```c
{device_model}
```

--- END OF CURRENT MODEL ---

{_render_apis_and_rules(contract, no_vio, extra=(slave_bug_blocker,))}

## Trace Log Schema:
The logs below are formatted as arrays containing the following fields: [Operation, Peripheral, Register, Memory Address, Register Value, Program Counter (PC)]. Pay close attention to the Register Value differences between Hardware and the Emulated Model.

--- START OF ANALYSIS DATA ---

## Platform:
{platform_name}

## Peripheral Name:
{peripheral_name}

{_build_analysis_section(diff_obj, state_data_with_instructions, no_encoder, hardware_log, emulation_log, peripheral_name, peripheral_ranges)}

--- END OF ANALYSIS DATA ---

Based on the trace data provided above and your knowledge of the peripheral's register definitions from the reference manual (bit field access types, reset values, hardware-owned vs software-writable bits), output:

## Required Output Format:

### 1. Previous Model Failure Analysis
A concise, one-paragraph summary explaining the most likely reason for the mismatches.

### 2. Register Analysis
A bulleted list of the important registers mentioned in the traces and their inferred functions.

{search_replace_prompting}
'''

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    output_filename = "initial_prompt.txt" if no_rca else "revised_prompt.txt"
    output_path = Path(out_dir) / output_filename
    output_path.write_text(final_prompt + "\n", encoding="utf-8")

    log.info(f"Prompt generated and can be accessed in the file {output_path}")
    return str(output_path)


def _build_compositional_model_source_blocks(model_to_path, show_prompt, max_model_chars):
    """Read each model file and format it as a labeled markdown source block.

    Returns a list of strings, one per entry in ``model_to_path``, suitable for
    joining with newlines and embedding in a prompt. Sources are truncated at
    ``max_model_chars``; when ``show_prompt`` is False the bodies are stubbed
    out (and a warning is logged because SEARCH/REPLACE corrections need the
    real source).
    """
    blocks = []
    for model_name, path in model_to_path.items():
        filename = os.path.basename(path)
        if show_prompt:
            source = Path(path).read_text(encoding="utf-8", errors="replace")
            if max_model_chars and len(source) > max_model_chars:
                source = source[:max_model_chars] + "\n/* ... truncated ... */"
        else:
            source = "/* model source hidden */"
            log.warning(
                f"show_prompt=False: model source for '{model_name}' will be hidden. "
                "SEARCH/REPLACE corrections will likely fail."
            )
        blocks.append(
            f"## Model: `{model_name}`  |  File: `{filename}`\n"
            f"```c\n"
            f"{source}\n"
            f"```"
        )
    return blocks


def _build_compositional_diff_blocks(peripherals, peripheral_results):
    """Format per-peripheral encoder diff data as MISMATCH/PASSING markdown blocks.

    ``peripheral_results`` maps each peripheral to ``(not_match, diff_obj)`` as
    produced by ``verify.verify_automata``. The output is consumed by the
    default and no_rca branches of ``iteration_prompt_gen_multiple_periph``.
    """
    blocks = []
    for periph in peripherals:
        not_match, diff_obj = peripheral_results[periph]
        status = "MISMATCH" if not_match else "PASSING"
        state_data_section = diff_obj.diff_state_data
        if state_data_section and not state_data_section.strip().startswith("[NO DATA"):
            state_data_section += "\n" + polling_interpretation_instructions
        blocks.append(textwrap.dedent(f"""\
        ## Peripheral: `{periph}`  [{status}]
        {"> This peripheral has trace mismatches that require a fix." if not_match else "> This peripheral is currently passing — do not regress it."}

        ### Initialization Sequence
```
        {diff_obj.diff_init_data}
```

        ### Detected Runtime Loops
```
        {diff_obj.diff_loop_pattern_data}
```

        ### Rare Value Transitions
        These are read values from LOW-entropy (status/control) registers that did NOT appear in the dominant loop patterns. They represent infrequent but important state changes that the model MUST handle correctly.
```
        {diff_obj.rare_transitions_data}
```

        ### Stateful Behavior Analysis
```
        {state_data_section}
```

        ### Register Entropy Analysis
```
        {diff_obj.diff_entropy_data}
```

        ### Runtime Data Accesses
```
        {diff_obj.diff_runtime_trace}
```

        ### ISR Analysis
        This file contains information about IRQs.
```
        {diff_obj.isr_analysis_data}
```

        {diff_obj.svd_bitfields_data}
        """).strip())
    return blocks


def _read_trace_strip_systick(log_path):
    """Read an io.log and drop the SysTick IRQ-taken/served bookkeeping lines.

    Those lines are not MMIO accesses and carry no register information; they
    are the only filter applied — no SVD-based address resolution, so this is
    safe to use for the no_encoder ablation path.
    """
    lines = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip()
            if "Vector = 0x0000000F" in stripped:
                continue
            lines.append(stripped)
    return "\n".join(lines)


def _write_prompt(out_dir, filename, content):
    """Persist a generated prompt to ``out_dir/filename`` and return the path."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(out_dir) / filename
    output_path.write_text(content + "\n", encoding="utf-8")
    log.info(f"Unified correction prompt written to {output_path}")
    return str(output_path)


def _validate_model_sources_map(model_sources_map, model_to_path, flag_name):
    """Ensure every -mname has an entry in model_sources_map.

    Raises ValueError on any missing/empty mapping. Returns the validated
    dict for convenience.
    """
    if not model_sources_map:
        raise ValueError(
            f"{flag_name} on a compositional (multi -mname) run requires "
            "model_sources_map (the --ms-map flag). Without it, each model's "
            "correction prompt cannot be built independently and the "
            "orchestration that RCA provides is preserved by accident."
        )
    missing = [m for m in model_to_path if not model_sources_map.get(m)]
    if missing:
        raise ValueError(
            f"{flag_name}: model_sources_map missing entries for "
            f"{missing}. Provide --ms-map MNAME=PERIPH1,PERIPH2,... for each --mname."
        )
    return model_sources_map


def _per_model_correction_prompt(
    *,
    mname, model_path, sources, peripheral_results, platform_name,
    apis_and_rules, mode,
):
    """Build the body of a per-model correction prompt for ``no_rca`` or
    ``no_verifier`` in compositional mode.

    ``mode`` is ``"no_rca"`` (diff data shown, full regen ask) or
    ``"no_verifier"`` (no diff data, generic regen ask). The prompt sees only
    this model's source and only this model's peripherals' diffs — it has no
    visibility into the other compositional model.
    """
    filename = os.path.basename(model_path)
    model_blocks = _build_compositional_model_source_blocks(
        {mname: model_path}, show_prompt=True, max_model_chars=120000,
    )

    if mode == "no_rca":
        # Filter peripheral_results to just this model's sources.
        model_results = {p: peripheral_results[p] for p in sources if p in peripheral_results}
        diff_blocks = _build_compositional_diff_blocks(sources, model_results)
        mismatch_list = [p for p, (nm, _) in model_results.items() if nm]
        if not mismatch_list:
            return None  # nothing to correct in this model
        analysis_section = textwrap.dedent(f"""\
        ## Your Task
        The following peripheral(s) covered by this model have trace mismatches: {", ".join(f"`{p}`" for p in mismatch_list)}.
        The Verifier diffs are shown below. Use them and the platform reference manual to produce a corrected complete C source file. Do not attempt SEARCH/REPLACE patches — output the full file content.

        ## Trace Log Schema
        Arrays of: [Operation, Peripheral, Register, Address, Value, PC].

        --- START OF ANALYSIS DATA ---

        ## Platform: {platform_name}

        {chr(10).join(diff_blocks)}

        --- END OF ANALYSIS DATA ---""")
    elif mode == "no_verifier":
        analysis_section = textwrap.dedent("""\
        ## Your Task
        The model file below was generated previously and failed verification against the hardware. No diff data is available. Use the platform reference manual and the broken model source to produce a corrected complete C source file.""")
    else:
        raise ValueError(f"Unknown per-model correction mode: {mode!r}")

    return textwrap.dedent(f"""\
    Take this prompt independent from previous prompt history.

    You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals.
    You have read the reference manual for {platform_name} with special familiarity with {", ".join(sources)}.

    {analysis_section}

    ## Model File Under Correction
    - `{mname}` → `{filename}`

    {apis_and_rules}

    --- START OF CURRENT MODEL ---

    {chr(10).join(model_blocks)}

    --- END OF CURRENT MODEL ---

    Output a complete corrected C source file in a ```c fenced block prefixed by `// FILE: {filename}`.
    """).strip()


def iteration_prompt_gen_multiple_periph(
    cm_path_hardware,
    cm_path_emulation,
    peripherals,           # all -p values, used for diff generation
    model_names,           # all -mname values
    model_to_path,         # {model_name: file_path}
    out_dir,
    show_prompt=True,
    max_model_chars=120000,
    # Ablation flags. All default to non-ablation (full pipeline) behavior.
    no_encoder=False,
    no_rca=False,
    no_verifier=False,
    no_vio=False,
    # Required when no_encoder=True (raw traces feed the prompt). Optional but
    # informative for no_verifier.
    hardware_log=None,
    emulation_log=None,
    # {mname: [periph_name, ...]} — required for no_rca and no_verifier in
    # compositional (multi-mname) mode. Identifies which peripherals each
    # model is responsible for, enabling per-model independent correction
    # prompts so cross-model orchestration is also ablated.
    model_sources_map=None,
    contract=None,
):
    """
    Generates correction prompts for the compositional multi-model verifier
    flow. Default mode produces a single unified prompt with structured per-
    peripheral diff blocks plus SEARCH/REPLACE instructions. The ablation
    flags select alternative correction strategies:

    - no_verifier: drop diff data entirely; show only the broken model source +
      a generic regeneration request (full code blocks). In compositional mode
      with model_sources_map set, splits into one prompt per model.
    - no_encoder: keep SEARCH/REPLACE strategy, but replace structured per-
      peripheral diff blocks with the raw hardware + emulation I/O traces.
      Joint by necessity (the raw trace cannot be split per peripheral).
    - no_rca:     keep structured diff blocks, but ask for full regeneration
      instead of SEARCH/REPLACE patches and drop the targeted RCA narrative.
      In compositional mode with model_sources_map set, splits into one
      prompt per model so cross-model orchestration is also ablated.
    - no_vio:     orthogonal lens; strips VIO APIs and the contract's
      LibVIO-only rules from whichever branch is selected above.

    Returns a single path string for joint prompts, or a {mname: path} dict
    when no_rca/no_verifier produce per-model splits.
    """
    if isinstance(peripherals, str):
        peripherals = [peripherals]
    else:
        peripherals = list(peripherals)

    summary_path = os.path.join(cm_path_hardware, "summary.txt")
    platform_name = parse_summary_file(summary_path).get("Platform", "Unknown Platform")

    # ── Shared building blocks (used by every branch below) ──────────────────
    model_source_blocks = _build_compositional_model_source_blocks(
        model_to_path, show_prompt, max_model_chars
    )
    file_reference = "\n    ".join(
        f"- `{model_name}` → `{os.path.basename(path)}`"
        for model_name, path in model_to_path.items()
    )
    apis_and_rules = _render_apis_and_rules(
        _contract(contract), no_vio, extra=(() if no_vio else (context_peripheral_instructions,)))

    # ── Branch: no_verifier — broken sources + generic "regenerate" message ──
    # In compositional mode, split into per-model independent prompts so the
    # cross-model orchestration that RCA provides is also ablated. In single-
    # mname mode, fall through to the joint prompt below.
    if no_verifier and len(model_to_path) > 1:
        _validate_model_sources_map(model_sources_map, model_to_path, "--no-verifier")
        out_paths = {}
        for mname, model_path in model_to_path.items():
            prompt = _per_model_correction_prompt(
                mname=mname,
                model_path=model_path,
                sources=model_sources_map[mname],
                peripheral_results={},  # unused in no_verifier mode
                platform_name=platform_name,
                apis_and_rules=apis_and_rules,
                mode="no_verifier",
            )
            # Sibling of out_dir, not subdir — survives verifier rmtree on next iter.
            base = Path(out_dir)
            sibling_dir = str(base.parent / f"{base.name}_{mname}")
            out_paths[mname] = _write_prompt(sibling_dir, "initial_prompt.txt", prompt)
        return out_paths

    # No diff data, no analysis. Written as initial_prompt.txt so the LLM
    # produces fresh full code blocks rather than SEARCH/REPLACE patches.
    if no_verifier:
        prompt = textwrap.dedent(f"""\
        Take this prompt independent from previous prompt history.

        You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals.
        You have read the reference manual for {platform_name} with special familiarity with {", ".join(peripherals)}.

        ## Your Task
        The model files below were generated previously and failed verification against the hardware. No diff data is available. Use the platform reference manual and the broken model sources to produce corrected complete C source code for every model file listed below.

        ## Model Files Under Correction
        {file_reference}

        {apis_and_rules}

        --- START OF CURRENT MODELS ---

        {chr(10).join(model_source_blocks)}

        --- END OF CURRENT MODELS ---

        Output a complete corrected C source file for each model above, in its own ```c fenced block prefixed by `// FILE: <filename>` so the framework can route each block to the right file.
        """).strip()
        return _write_prompt(out_dir, "initial_prompt.txt", prompt)

    # ── Branch: no_encoder — raw HW/EM traces in place of encoder diffs ──────
    # SEARCH/REPLACE strategy preserved. Skips verify_automata entirely
    # because we are not using its structured output.
    if no_encoder:
        if not hardware_log:
            raise ValueError(
                "iteration_prompt_gen_multiple_periph: no_encoder=True requires hardware_log"
            )
        raw_hw = _read_trace_strip_systick(hardware_log)
        em_section = ""
        if emulation_log:
            raw_em = _read_trace_strip_systick(emulation_log)
            # Cap emulation trace at 2× hardware length to defend against
            # infinite-loop models flooding the prompt.
            hw_lines = raw_hw.count("\n") + 1
            em_lines = raw_em.split("\n")
            if len(em_lines) > hw_lines * 2:
                truncated = len(em_lines)
                raw_em = "\n".join(em_lines[: hw_lines * 2])
                raw_em += (
                    f"\n\n[TRUNCATED: emulation trace had {truncated} lines, "
                    f"capped at {hw_lines * 2} (2x hardware trace). "
                    "The model likely contains an infinite polling loop.]"
                )
            em_section = (
                "\n\n## Raw Emulated Model I/O Trace\n"
                "Compare against the hardware trace above to identify divergence points.\n"
                f"```\n{raw_em}\n```"
            )

        prompt = textwrap.dedent(f"""\
        Take this prompt independent from previous prompt history.

        You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals.
        You have read the reference manual for {platform_name} with special familiarity with {", ".join(peripherals)}.

        ## Your Task
        The peripheral models below failed verification. Compare the raw hardware and emulated I/O traces to identify the divergence and produce SEARCH/REPLACE patches against the model files. A mismatch attributed to one peripheral may originate in a *different* model file — reason across all models before deciding where the fix belongs.

        ## Model Files Under Correction
        You may produce SEARCH/REPLACE blocks for any or all of these files:
        {file_reference}
        Each SEARCH/REPLACE block MUST begin with a comment identifying its target file:
        `// FILE: <filename>`

        {apis_and_rules}

        --- START OF CURRENT MODELS ---

        {chr(10).join(model_source_blocks)}

        --- END OF CURRENT MODELS ---

        --- START OF RAW TRACES ---

        ## Platform: {platform_name}

        ## Raw Hardware I/O Trace
        ```
        {raw_hw}
        ```{em_section}

        --- END OF RAW TRACES ---

        {search_replace_prompting}
        """).strip()
        return _write_prompt(out_dir, "revised_prompt.txt", prompt)

    # ── 1. Run verification for all peripherals ──────────────────────────────
    peripheral_results = {}   # {periph: (not_match, diff_obj)}
    any_mismatch = False

    for periph in peripherals:
        not_match, diff_obj = verify.verify_automata(
            automata1=cm_path_hardware,
            automata2=cm_path_emulation,
            peripheral=periph
        )
        peripheral_results[periph] = (not_match, diff_obj)
        if not_match:
            any_mismatch = True

    if not any_mismatch:
        log.info("All peripherals passing — no correction prompt needed.")
        return None

    # ── Branch: no_rca — diffs shown, generic message, full regeneration ─────
    # In compositional mode, split into per-model independent prompts so the
    # cross-model orchestration RCA provides is also ablated. Each LLM call
    # sees only its own model's source + only its peripherals' diff blocks
    # and has no awareness of the other model.
    if no_rca and len(model_to_path) > 1:
        _validate_model_sources_map(model_sources_map, model_to_path, "--no-rca")
        out_paths = {}
        for mname, model_path in model_to_path.items():
            sources = model_sources_map[mname]
            prompt = _per_model_correction_prompt(
                mname=mname,
                model_path=model_path,
                sources=sources,
                peripheral_results=peripheral_results,
                platform_name=platform_name,
                apis_and_rules=apis_and_rules,
                mode="no_rca",
            )
            if prompt is None:
                log.info(
                    f"  No-RCA: skipping `{mname}` — no mismatches in its peripherals."
                )
                continue
            # Sibling of out_dir, not subdir — survives verifier rmtree on next iter.
            base = Path(out_dir)
            sibling_dir = str(base.parent / f"{base.name}_{mname}")
            out_paths[mname] = _write_prompt(sibling_dir, "initial_prompt.txt", prompt)
        if not out_paths:
            log.info("All peripherals passing — no correction prompt needed.")
            return None
        return out_paths

    if no_rca:
        diff_blocks = _build_compositional_diff_blocks(peripherals, peripheral_results)
        mismatch_list = [p for p, (nm, _) in peripheral_results.items() if nm]
        prompt = textwrap.dedent(f"""\
        Take this prompt independent from previous prompt history.

        You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals.
        You have read the reference manual for {platform_name} with special familiarity with {", ".join(peripherals)}.

        ## Your Task
        The following peripheral(s) have trace mismatches: {", ".join(f"`{p}`" for p in mismatch_list)}.
        The Verifier diffs are shown below. Use them and the platform reference manual to produce corrected complete C source code for every model file listed. Do not attempt SEARCH/REPLACE patches — output full file content for each model.

        ## Model Files Under Correction
        {file_reference}

        {apis_and_rules}

        ## Trace Log Schema
        Arrays of: [Operation, Peripheral, Register, Address, Value, PC].
        Pay close attention to Value differences between Hardware and Emulated.

        --- START OF CURRENT MODELS ---

        {chr(10).join(model_source_blocks)}

        --- END OF CURRENT MODELS ---

        --- START OF ANALYSIS DATA ---

        ## Platform: {platform_name}

        {chr(10).join(diff_blocks)}

        --- END OF ANALYSIS DATA ---

        Output a complete corrected C source file for each model above, in its own ```c fenced block prefixed by `// FILE: <filename>` so the framework can route each block to the right file.
        """).strip()
        return _write_prompt(out_dir, "initial_prompt.txt", prompt)

    # ── Default branch: structured per-peripheral diffs + SEARCH/REPLACE ─────
    peripheral_diff_blocks = _build_compositional_diff_blocks(peripherals, peripheral_results)
    mismatch_list = [p for p, (nm, _) in peripheral_results.items() if nm]

    prompt_start = textwrap.dedent(f"""\
    Take this prompt independent from previous prompt history.

    You are an expert reverse engineer specializing in embedded systems and \
writing C emulation for peripherals.
    You have read the reference manual for {platform_name} with special \
familiarity with {", ".join(peripherals)}.

    ## Your Task
    The following peripheral(s) have trace mismatches: {", ".join(f"`{p}`" for p in mismatch_list)}.
    Analyze the diffs below and correct whichever model file(s) are responsible.
    A mismatch in one peripheral may be caused by a bug in a *different* model \
(e.g. `ADC1` calling `api_dma_request` with a wrong controller ID or stream ID will manifest as \
a DMA model failure). Reason across all models before deciding where the fix belongs.

    ## Model Files Under Correction
    You may produce SEARCH/REPLACE blocks for any or all of these files:
    {file_reference}
    Each SEARCH/REPLACE block MUST begin with a comment identifying its target file:
    `// FILE: <filename>`

    {apis_and_rules}

    ## Trace Log Schema
    Arrays of: [Operation, Peripheral, Register, Address, Value, PC].
    Pay close attention to Value differences between Hardware and Emulated.

    --- START OF CURRENT MODELS ---

    {chr(10).join(model_source_blocks)}

    --- END OF CURRENT MODELS ---

    --- START OF ANALYSIS DATA ---

    ## Platform: {platform_name}

    """).strip()

    prompt_end = textwrap.dedent(f"""\
    --- END OF ANALYSIS DATA ---

    Based on the trace data above and your knowledge of the peripheral's register definitions from the reference manual (bit field access types, reset values, hardware-owned vs software-writable bits), output:

    ### 1. Cross-Model Failure Analysis
    For each [MISMATCH] peripheral, identify:
    - The root cause
    - Which model file contains the bug (may differ from the peripheral's own model)
    - Whether fixing it risks regressing any [PASSING] peripheral

    ### 2. Register Analysis
    Bulleted list of registers involved in mismatches and their inferred roles.

    {search_replace_prompting}
    """).strip()

    final_prompt = (
        prompt_start + "\n\n"
        + "\n\n".join(peripheral_diff_blocks) + "\n\n"
        + prompt_end
    ).strip()

    return _write_prompt(out_dir, "revised_prompt.txt", final_prompt)
