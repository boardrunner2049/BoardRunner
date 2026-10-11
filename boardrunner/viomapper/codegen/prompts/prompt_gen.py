import os
import glob
import logging
import textwrap
import click
from pathlib import Path

from boardrunner.viomapper.codegen.prompts.contract import load_contract
from boardrunner.viomapper.encoder.summary import parse_summary_file

log = logging.getLogger(__name__)


context_peripheral_instructions = """\
### How to Use Context Peripheral Data
- Do **not** generate a device model for context peripherals.
- Use their trace data only to understand how the target model interacts with \
them at runtime (e.g., which stream IDs are used, when a DMA request is \
triggered, what IRQ line is shared).
- If the target model drives or is driven by a context peripheral, express that \
relationship using the inter-peripheral APIs described above.
"""

host_io_section = """\
## Host-Side I/O Setup (if needed)
After generating the model, provide the exact host command(s) required to create \
and manage any virtual I/O endpoint the model connects to (e.g., a pseudo-terminal, \
a named pipe, a TAP interface). List commands in run order. If no external command \
is required for the peripheral to function, output exactly: \
No host-side setup required.
"""

api_missing_note = """\
### Missing API Policy (HARD BLOCKER)
If the model requires an API that is not listed above, you MUST stop and NOT \
generate the device model. Instead:
1. Clearly name the missing API and explain why it is required for this model.
2. Propose a precise signature for the missing API in the following format:
   - **Name**: `api_<domain>_<action>` (e.g., `api_can_send_frame`)
   - **Inputs**: list each parameter with its C type and a one-line description
   - **Output**: return type and meaning
   - **Description**: one paragraph explaining what the API does and when the \
model would call it
3. STOP here. Do not generate the model. Do not attempt workarounds or \
placeholder implementations. The user will add the API to the framework and \
re-run generation.

Do NOT generate partial or placeholder models when a required API is missing — \
this creates cascading failures in the emulation pipeline.
"""


# ── The model contract (rules, LibVIO API, host functions) comes from LibVIO ─
# See contract.py. Everything below is BoardRunner's own: how the pipeline
# asks for a model, not what a model is.

def _contract(contract):
    return contract if contract is not None else load_contract()


def _render_apis(contract, no_vio, audiences=("model",)):
    """The functions a model may call: host functions and, unless no_vio, LibVIO."""
    return (
        "## Available APIs\n"
        "You **must** use the following APIs to construct the device model. "
        "Pay close attention to the callback signatures.\n\n"
        + contract.api(audiences, vio=not no_vio)
    )


def _includes_note(no_vio):
    if no_vio:
        return "Including `<fastdyn/device_model.h>` gives you access to all the functions listed above."
    return ("Including `<fastdyn/device_model.h>` and `<vio/vio.h>` gives you access to all the "
            "functions listed above.")


def _model_sketch(name, no_vio=False):
    """The shape of a device model (FastDyn model ABI v2) named after ``name``."""
    lower = name.lower()
    vio_include = "" if no_vio else "#include <vio/vio.h>\n"
    return f"""```c
// Device Model for {name}
#include <fastdyn/device_model.h>
{vio_include}#include <stdlib.h>

// Inferred Register Functions:
// ... add registers here ...

// All state of one device; the same model may serve several devices
typedef struct {{
    uint64_t base;  // from dev->ranges[0].base
    // ... register state ...
}} {name}State;

// This function will emulate all device reads
static uint64_t {lower}_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {{
    {name}State *s = opaque;
    // ... return register value based on offset (addr - s->base) ...
}}

// This function will emulate all device writes
static void {lower}_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {{
    {name}State *s = opaque;
    // ... update register state based on offset (addr - s->base) and value ...
}}

// Called once per device; the returned state is passed as opaque to _read/_write
static void *{lower}_init(const FdDevice *dev, const char *config_json, const FdHost *host) {{
    {name}State *s = calloc(1, sizeof(*s));
    if (!s) return NULL;
    s->base = dev->ranges[0].base;
    // ... reset values, settings from config_json ...
    return s;
}}

const FdModel fastdyn_model = {{
    FASTDYN_MODEL_ABI_FIELDS,
    .init = {lower}_init,
    .read = {lower}_read,
    .write = {lower}_write,
}};
```"""


def _render_apis_and_rules(contract, no_vio, extra=()):
    """APIs, the missing-API policy, the contract's rules, ``extra`` blocks and
    the host-I/O section (the VIO-only parts are left out with no_vio)."""
    parts = [
        _render_apis(contract, no_vio),
        "" if no_vio else api_missing_note,
        contract.rules(vio=not no_vio),
        *extra,
        "" if no_vio else host_io_section,
    ]
    return "\n\n".join(p for p in parts if p)


def initial_prompt_gen_multiple_periphs(analysis_dir, model_name, peripherals, out_dir, model_sources, no_vio=False,
                                        contract=None, **kwargs):
    log.info("Generating Prompt for LLM")
    if 'user_obs' in kwargs:
        pass  # Deprecated — observability is now always inferred from the contract's rules

    if no_vio:
        log.info("Ablation mode: --no-vio enabled. VIO APIs stripped from prompt.")

    final_prompt = generate_prompt_multiple(
        analysis_dir=analysis_dir,
        model_name=model_name,
        peripherals=peripherals,
        model_sources=model_sources,
        no_vio=no_vio,
        contract=contract,
    )

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(out_dir) / "initial_prompt.txt"
    output_path.write_text(final_prompt + "\n", encoding="utf-8")

    log.info(f"Prompt generated and can be accessed in the file {output_path}")
    return str(output_path)


def initial_prompt_gen(analysis_dir, peripheral, out_dir, no_vio=False, contract=None):
    log.info("Generating Prompt for LLM")
    if no_vio:
        log.info("Ablation mode: --no-vio enabled. VIO APIs stripped from prompt.")
    # Construct the path from the base directory and the peripheral name
    peripheral_path = os.path.join(analysis_dir, peripheral)

    final_prompt = generate_prompt(peripheral_path, no_vio=no_vio, contract=contract)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(out_dir) / "initial_prompt.txt"
    output_path.write_text(final_prompt + "\n", encoding="utf-8")

    log.info(f"Prompt generated and can be accessed in the file {output_path}")
    return str(output_path)


def read_file_content(filepath: str) -> str:
    """Reads the entire content of a file, returning a helpful message if not found."""
    if not os.path.exists(filepath):
        return f"[NO DATA — file not found: {os.path.basename(filepath)}]"
    try:
        with open(filepath, 'r') as f:
            content = f.read().strip()
            return content if content else "[NO DATA — file is empty]"
    except Exception as e:
        return f"[NO DATA — read error: {e}]"

def generate_prompt(peripheral_directory: str, no_vio: bool = False, contract=None) -> str:
    """
    Generates a detailed prompt for an LLM based on analysis files in a directory.

    Args:
        peripheral_directory: Path to the analysis directory for the peripheral.
        no_vio: If True, strip VIO APIs from the prompt (ablation mode).
        contract: The LibVIO model contract (default: load_contract()).
    """
    if not os.path.isdir(peripheral_directory):
        raise FileNotFoundError(
            f"Analysis directory not found: {peripheral_directory}. "
            f"Ensure you have run the analysis script first."
        )

    peripheral_name = os.path.basename(peripheral_directory)

    # Find and parse the summary.txt file from the parent directory
    parent_dir = os.path.dirname(peripheral_directory)
    summary_path = os.path.join(parent_dir, "summary.txt")
    summary_info = parse_summary_file(summary_path)
    platform_name = summary_info.get("Platform", "Unknown Platform")
    isr_analysis = os.path.join(peripheral_directory, "isr_analysis.txt")

    # Read all other analysis files
    init_data = read_file_content(os.path.join(peripheral_directory, "init.txt"))
    state_data = read_file_content(os.path.join(peripheral_directory, "state.txt"))
    entropy_data = read_file_content(os.path.join(peripheral_directory, "entropy.txt"))
    rare_transitions_data = read_file_content(os.path.join(peripheral_directory, "rare_transitions.txt"))
    loop_files = sorted(glob.glob(os.path.join(peripheral_directory, "loop_pattern_*.txt")))
    isr_analysis_data = read_file_content(isr_analysis)
    svd_bitfields_data = read_file_content(os.path.join(peripheral_directory, "svd_bitfields.txt"))

    loop_data_list = []
    if not loop_files:
        loop_data_list.append("No repeating loop patterns were detected for this peripheral.")
    else:
        for loop_file in loop_files:
            loop_data_list.append(f"--- Contents of {os.path.basename(loop_file)} ---\n{read_file_content(loop_file)}")
    loop_data = "\n\n".join(loop_data_list)

    # When VIO APIs are stripped (A3 ablation), the contract's LibVIO-only
    # rules and the VIO guidance go too, so the LLM has no hints about
    # PTY/I2C/SPI/signal APIs.
    apis_and_rules = _render_apis_and_rules(_contract(contract), no_vio)

    prompt = f"""
Take this prompt independent from previous prompt history.

You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals. You have read the reference manual for {platform_name} with special familiarity with {peripheral_name.lower()} peripheral.
Your task is to analyze the following summary of MMIO trace data and generate a complete C device model.

{apis_and_rules}

--- START OF ANALYSIS DATA ---

## Platform:
{platform_name}

## Peripheral Name:
{peripheral_name}

## Initialization Sequence (`init.txt`):
This file contains all accesses that occur before the main runtime loop begins.
```
{init_data}
```

## Detected Runtime Loops (`loop_pattern_*.txt`):
These files contain the most common repeating sequences of operations during runtime.
```
{loop_data}
```

## Rare Value Transitions (`rare_transitions.txt`):
These are read values from LOW-entropy (status/control) registers that did NOT appear in the dominant loop patterns above. They represent infrequent but important state changes that the model MUST handle correctly. Pay close attention to these values — they reveal how the register behaves in a different operational phase (e.g. data available vs. idle).
```
{rare_transitions_data}
```

## Stateful Behavior Analysis (`state.txt`):
This file identifies programming patterns like Read-Modify-Write (RMW), which indicate stateful registers.
```
{state_data}
```

## Register Entropy Analysis (`entropy.txt`):
This file measures the randomness of values read from registers. High entropy suggests data registers, while low entropy suggests status registers.
```
{entropy_data}
```

## ISR Analysis (`isr_analysis.txt`)
This file contains information about IRQs.
```
{isr_analysis_data}
```

{svd_bitfields_data}

--- END OF ANALYSIS DATA ---

Based on the trace data provided above and your knowledge of the peripheral's register definitions from the reference manual (bit field access types, reset values, hardware-owned vs software-writable bits), generate the complete C source code for the device model. Follow the required output format precisely.

## Required Output Format:

### 1. High-Level Summary
A concise, one-paragraph summary of this peripheral's likely purpose and overall behavior, considering the platform context.

### 2. Register Analysis
A bulleted list of the important registers mentioned in the traces and their inferred functions.

### 3. C Device Model Source Code
The C source code for MMIO read and write callback for {peripheral_name} emulation and any initialization you need for the emulation only. The code must be fully self-contained and ready to be compiled. {_includes_note(no_vio)}

{_model_sketch(peripheral_name, no_vio)}
"""
    return prompt.strip()

def generate_prompt_no_encoder(hardware_log: str, peripheral_name: str, platform_name: str,
                               peripheral_ranges: list = None, no_vio: bool = False,
                               model_name: str = None, model_sources=None, contract=None) -> str:
    """Generate a prompt using the raw I/O trace instead of the Encoder's compact automaton.

    This is the A1 ablation variant. The prompt contains:
    - The raw io.log (filtered to the target peripheral's address range if known)
    - The VIO API definitions (unless no_vio is also set)
    - The same framework rules and output format as the full pipeline

    No SVD annotations, no pattern mining, no entropy analysis, no ISR detection.

    Args:
        hardware_log: Path to the raw hardware_log/io.log file.
        peripheral_name: Name of the peripheral (e.g., "UART0", "SPI0").
        platform_name: Platform identifier (e.g., "Max78000").
        peripheral_ranges: Optional list of (start, end) address tuples to filter trace lines.
        no_vio: If True, also strip VIO APIs (combines A1+A3 ablation).
        model_name: Compositional model name from `-mname`; falls back to peripheral_name.
        model_sources: Iterable of peripherals from `-ms`; falls back to [peripheral_name].
        contract: The LibVIO model contract (default: load_contract()).
    """
    # Read the raw trace, stripping only internal emulator bookkeeping
    # (SysTick IRQ taken/served) that are not MMIO accesses.
    # No SVD-based address filtering — the LLM must identify the target
    # peripheral's registers on its own for a clean A1 ablation.
    lines = []
    with open(hardware_log, "r", encoding="utf-8") as f:
        for line in f:
            if 'Vector = 0x0000000F' in line:
                continue
            lines.append(line.rstrip())
    raw_trace = "\n".join(lines)

    apis_and_rules = _render_apis_and_rules(_contract(contract), no_vio)

    effective_model_name = model_name if model_name else peripheral_name
    sources_list = list(model_sources) if model_sources else [peripheral_name]
    sources_section = "\n".join(f"- {p}" for p in sources_list)

    prompt = f"""
Take this prompt independent from previous prompt history.

You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals. You have read the reference manual for {platform_name} with special familiarity with {effective_model_name.lower()} peripheral.
Your task is to analyze the following raw MMIO I/O trace and generate a complete C device model.

{apis_and_rules}

--- START OF RAW I/O TRACE ---

## Platform:
{platform_name}

## Model Name (name the model's functions after it):
{effective_model_name}

## Peripherals to Model (covered by this single C file):
{sources_section}

## Raw Hardware I/O Trace:
The following is the raw MMIO trace captured during hardware execution.
Each line represents a single register read or write with timestamp, address, value, and size.
You must infer the register layout, initialization sequence, runtime behavior, and interrupt patterns from this trace.
```
{raw_trace}
```

--- END OF RAW I/O TRACE ---

Based on the trace data provided above and your knowledge of the peripheral's register definitions from the reference manual (bit field access types, reset values, hardware-owned vs software-writable bits), generate the complete C source code for the device model. Follow the required output format precisely.

## Required Output Format:

### 1. High-Level Summary
A concise, one-paragraph summary of this peripheral's likely purpose and overall behavior, considering the platform context.

### 2. Register Analysis
A bulleted list of the important registers mentioned in the traces and their inferred functions.

### 3. C Device Model Source Code
The C source code for MMIO read and write callback for {effective_model_name} emulation and any initialization you need for the emulation only. The code must be fully self-contained and ready to be compiled. {_includes_note(no_vio)}

{_model_sketch(effective_model_name, no_vio)}
"""
    return prompt.strip()


def _strip_commented_out_blocks(source: str, min_run: int = 10) -> str:
    """Remove large contiguous blocks of //-commented lines from C source.

    Inline comments that appear alongside active code are left intact.
    Only runs of `min_run` or more consecutive lines where every non-blank
    line starts with '//' are removed — these are almost always dead code
    blocks that were commented out, not useful documentation.
    """
    lines = source.splitlines()
    result = []
    i = 0
    while i < len(lines):
        # Scan forward to measure the length of a //-only run starting at i
        j = i
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped == '' or stripped.startswith('//'):
                j += 1
            else:
                break
        run_len = j - i
        if run_len >= min_run:
            # Drop the block; skip to end of run
            i = j
        else:
            result.extend(lines[i:j])
            i = j
            if i < len(lines):
                result.append(lines[i])
                i += 1
    return '\n'.join(result)


def slave_model_gen(peripheral_name, platform_name, out_dir, slave_firmware_path, reference_model_path, slave_type="i2c",
                    contract=None):
    '''
    based on the slave firmware code and the existing reference code, generate a C model for the slave.
    '''
    log.info("Generating Prompt for LLM")

    with open(slave_firmware_path, 'r') as f:
        slave_firmware = _strip_commented_out_blocks(f.read().strip())

    with open(reference_model_path, 'r') as f:
        reference_model = f.read().strip()

    if slave_type == "spi":
        slave_callbacks = """\
    These are the slave's functions — the ONLY entry points LibVIO calls on the slave (see "Slave models" above).
    Their names are fixed. Do not rename them or add new registration functions.
    - `vio_spi_slave_init`
    - `vio_spi_slave_set_cs`
    - `vio_spi_slave_transfer`
    - `vio_slave_free` (optional)
"""
    else:
        slave_callbacks = """\
    These are the slave's functions — the ONLY entry points LibVIO calls on the slave (see "Slave models" above).
    Their names are fixed. Do not rename them or add new registration functions.
    - `vio_i2c_slave_init`
    - `vio_i2c_slave_event`
    - `vio_i2c_slave_send`
    - `vio_i2c_slave_recv`
    - `vio_slave_free` (optional)
"""

    slave_gen_prompt = f"""
Take this prompt independent from previous prompt history.

You are an expert reverse engineer specializing in embedded systems and writing C emulation for peripherals. You have read the reference manual for {platform_name} with special familiarity with {peripheral_name.lower()} peripheral.
Your task is to analyze the following firmware of the {peripheral_name} slave and a reference c model.

{_render_apis(_contract(contract), no_vio=False, audiences=("model", "slave"))}

{api_missing_note}

## Slave Callback Interface
{slave_callbacks}

{host_io_section}

## Slave Firmware
{slave_firmware}

## Slave Model Reference Code
{reference_model}

## Expected Slave Model Structure
Your generated slave model MUST follow this structural pattern:
```c
#include <vio/slave.h>
#include <stdbool.h>
#include <stdlib.h>

const int vio_slave_abi = VIO_SLAVE_ABI_VERSION;

// 1. State struct with register array and protocol state: one per slave
//    instance, returned by init and passed back as ctx (never globals)
typedef struct {{
    uint8_t regs[256];
    bool    expect_reg_addr;   // I2C: next byte is register pointer
    uint8_t reg_ptr;           // current register pointer
}} <name>_state_t;

// 2. Defaults loader (called on init and soft-reset)
static void load_defaults(<name>_state_t *s) {{ ... }}

// 3. Init: create the instance (name and config_json come from the bus config)
void *vio_i2c_slave_init(const char *name, const char *config_json) {{   // SPI: vio_spi_slave_init
    <name>_state_t *s = calloc(1, sizeof(*s));
    if (s) load_defaults(s);
    return s;
}}

// 4. The REQUIRED functions (fixed names, each receives ctx first):
//    I2C: vio_i2c_slave_event, vio_i2c_slave_send, vio_i2c_slave_recv
//    SPI: vio_spi_slave_set_cs, vio_spi_slave_transfer
//    Optional: vio_slave_free
```

## Required Output Format

### 1. High-Level Summary
A concise, one-paragraph summary of this slave device's purpose and protocol behavior.

### 2. Register Map
A bulleted list of the slave's internal registers and their functions, inferred from the firmware and reference model.

### 3. C Slave Model Source Code
The complete, self-contained C source file. Including `<vio/slave.h>` gives you the slave interface; `<fastdyn/device_model.h>` and `<vio/vio.h>` give you the other functions listed above.
The code must compile as a shared library.
"""

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(out_dir) / "initial_prompt.txt"
    output_path.write_text(slave_gen_prompt + "\n", encoding="utf-8")

    log.info(f"Prompt generated and can be accessed in the file {output_path}")
    return str(output_path)

def _resolve_roles(peripherals, model_name, model_sources=None):
    """
    Returns:
        roles   : dict {periph_str: 'SOURCE' | 'CONTEXT'}
        sources : list of SOURCE peripheral names
    """
    if model_sources:
        # Explicit override — trust the user
        model_sources_lower = {s.strip().lower() for s in model_sources}
        roles = {
            p: ("SOURCE" if p.strip().lower() in model_sources_lower else "CONTEXT")
            for p in peripherals
        }
    else:
        # Heuristic: exact match OR model_name contains periph name as substring
        model_lower = model_name.strip().lower()
        roles = {}
        for p in peripherals:
            p_lower = p.strip().lower()
            if p_lower == model_lower or p_lower in model_lower:
                roles[p] = "SOURCE"
            else:
                roles[p] = "CONTEXT"

    sources = [p for p, r in roles.items() if r == "SOURCE"]

    if not sources:
        raise ValueError(
            f"Could not resolve any SOURCE peripheral for model '{model_name}'.\n"
            f"Peripherals given: {list(peripherals)}\n"
            f"None matched by exact name or substring.\n"
            f"Use -ms/--model-source to specify explicitly.\n"
            f"Example: -ms DMA1 -ms DMAMUX1"
        )

    return roles, sources

def generate_prompt_multiple(analysis_dir, model_name, peripherals, model_sources, no_vio=False, contract=None):
    """
    Generates a detailed prompt for an LLM based on analysis files in a directory.
    `peripherals` can be a tuple/list (Click multiple=True) or a single string.

    When ``no_vio`` is True, VIO APIs, the contract's LibVIO-only rules and
    the context-peripheral / host-I/O guidance are stripped so the prompt
    advertises only the emulator's host functions.
    """
    if isinstance(peripherals, str):
        peripherals = [peripherals]
    else:
        peripherals = list(peripherals)

    # Resolve roles
    try:
        roles, sources = _resolve_roles(peripherals, model_name, model_sources)
    except ValueError as e:
        raise click.UsageError(str(e))

    # Parse summary once (it lives in analysis_dir/summary.txt per your layout)
    summary_path = os.path.join(analysis_dir, "summary.txt")
    summary_info = parse_summary_file(summary_path)
    platform_name = summary_info.get("Platform", "Unknown Platform")

    blocks = []
    for periph in peripherals:
        peripheral_directory = os.path.join(analysis_dir, periph)
        peripheral_name = os.path.basename(peripheral_directory)

        init_data    = read_file_content(os.path.join(peripheral_directory, "init.txt"))
        state_data   = read_file_content(os.path.join(peripheral_directory, "state.txt"))
        entropy_data = read_file_content(os.path.join(peripheral_directory, "entropy.txt"))

        isr_path = os.path.join(peripheral_directory, "isr_analysis.txt")
        isr_analysis_data = read_file_content(isr_path)
        svd_bitfields_data = read_file_content(os.path.join(peripheral_directory, "svd_bitfields.txt"))

        loop_files = sorted(glob.glob(os.path.join(peripheral_directory, "loop_pattern_*.txt")))
        if not loop_files:
            loop_data = "No repeating loop patterns were detected for this peripheral."
        else:
            loop_chunks = []
            for loop_file in loop_files:
                loop_chunks.append(
                    f"--- Contents of {os.path.basename(loop_file)} ---\n{read_file_content(loop_file)}"
                )
            loop_data = "\n\n".join(loop_chunks)

        role = roles[periph]
        if role == "SOURCE":
            role_note = (
                f"[SOURCE] — This peripheral's trace data is the PRIMARY BEHAVIORAL SOURCE "
                f"for modeling `{model_name}`. Generate `{model_name}` using this data as "
                f"your main reference. The output model name is `{model_name}` rather than "
                f"`{periph}` because this model may be a composite covering additional "
                f"hardware blocks (see address ranges below if present)."
            )
        else:
            role_note = (
                f"[CONTEXT] — Do NOT generate a model for `{periph}`. Use this data only "
                f"to understand how `{model_name}` interacts with `{periph}` at runtime."
            )

        block = textwrap.dedent(f"""\
        ## Peripheral: {periph}  [{role}]
        > {role_note}

        ## Initialization Sequence (`init.txt`)
        This file contains all accesses that occur before the main runtime loop begins.
        ```
        {init_data}
        ```

        ## Detected Runtime Loops (`loop_pattern_*.txt`)
        These files contain the most common repeating sequences of operations during runtime.
        ```
        {loop_data}
        ```

        ## Stateful Behavior Analysis (`state.txt`)
        This file identifies programming patterns like Read-Modify-Write (RMW), which indicate stateful registers.
        ```
        {state_data}
        ```

        ## Register Entropy Analysis (`entropy.txt`)
        This file measures the randomness of values read from registers. High entropy suggests data registers,
        while low entropy suggests status registers.
        ```
        {entropy_data}
        ```

        ## ISR Analysis (`isr_analysis.txt`)
        This file contains information about IRQs.
        ```
        {isr_analysis_data}
        ```

        {svd_bitfields_data}
        """)
        blocks.append(block)

    apis_and_rules = _render_apis_and_rules(
        _contract(contract), no_vio, extra=(() if no_vio else (context_peripheral_instructions,)))

    prompt_start = textwrap.dedent(f"""\
    Take this prompt independent from previous prompt history.

    You are an expert reverse engineer specializing in embedded systems and writing C emulation \
    for peripherals in a QEMU-based framework.
    You have read the reference manual for {platform_name} with deep familiarity with \
    {", ".join(peripherals)}.

    ## Your Task
    Generate a **single, complete C device model** for: `{model_name}`

    The analysis data below covers **multiple peripherals**: {", ".join(peripherals)}.
    One of these is the **target** (`{model_name}`) — the model you are generating.
    The others are **context peripherals** — provided only because `{model_name}` has a \
    runtime dependency on them (e.g., it triggers DMA, shares a bus, raises an IRQ to another block).

    ### Dependency Check
    Before generating code, briefly state:
    1. Which peripheral(s) are context (not the target).
    2. What the runtime relationship is between `{model_name}` and each context peripheral.
    3. Which API(s) from the list below implement that relationship.

    If you cannot infer a meaningful relationship from the trace data, and the context peripheral \
    data provides no useful information for modeling `{model_name}`, state that clearly and \
    **ignore** the context peripheral — do not let it block code generation.

    {apis_and_rules}

    --- START OF ANALYSIS DATA ---

    ## Platform
    {platform_name}

    ## TARGET MODEL: {model_name}

    """)

    # f-string + doubled braces to emit literal C braces
    prompt_end = textwrap.dedent(f"""\
    --- END OF ANALYSIS DATA ---

    Based on the trace data above and your knowledge of the peripheral's register definitions from the reference manual (bit field access types, reset values, hardware-owned vs software-writable bits), generate the complete C source for `{model_name}`.

    ## Required Output Format

    ### 1. Dependency Summary
    - Target model: `{model_name}`
    - Context peripheral(s) and their role (e.g., "DMA — `{model_name}` triggers a DMA request after conversion complete")
    {"" if no_vio else "- Inter-peripheral APIs used and why"}

    ### 2. Register Analysis
    Bulleted list of important registers and their inferred functions.

    ### 3. C Device Model Source Code
    Self-contained C source for `{model_name}` only. {_includes_note(no_vio)}
    @@MODEL_SKETCH@@
    """).replace("@@MODEL_SKETCH@@", _model_sketch(model_name, no_vio))

    # Update prompt_start to show composition clearly
    composition_note = textwrap.dedent(f"""\
    ## Model Composition
    - **Trace sources** (primary behavioral data): {', '.join(f'`{s}`' for s in sources)}
    - **Context only** (do not model): {', '.join(f'`{p}`' for p in peripherals if roles[p] == 'CONTEXT') or 'None'}
    - **Output model name**: `{model_name}`

    """)

    # Insert composition_note + ranges_block between the blocks and prompt_end
    return (
        prompt_start
        + composition_note
        + "\n\n".join(blocks)
        + "\n\n"
        + prompt_end
    ).strip()
