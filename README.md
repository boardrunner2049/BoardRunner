# BoardRunner

BoardRunner rehosts embedded firmware automatically. It observes the firmware
running on the real board (hardware in the loop), learns a model of each
peripheral from that trace (VIOMapper: Encoder, CodeGen, Verifier, RCA), and
then runs the firmware without the board, on [FastDyn](deps/fastdyn) with the
learned models and [LibVIO](https://github.com/PSecLab/LibVIO).

> **Status:** BoardRunner is being moved out of the FastDyn repository into
> this one. The VIOMapper code, trace capture and the `boardrunner` command
> are here; the examples and evaluation follow.

## The paper version

The version evaluated in the CCS'26 paper is FastDyn's `boardrunner/` tree
at the FastDyn tag `ccs26-artifact`. The first `main` commit of this
repository will be that snapshot (tag `v1.0-ccs26`), with the artifact
DOI: **TODO(DOI)**. Later commits restructure the code; models generated on
them may be deprecated until they are migrated to FastDyn's device model
interface (ABI v2) and LibVIO v1.

TODO: migrate all generated models once the model interface and the LibVIO
contract are stable (the hardware-free F103RB examples are migrated first).

## Development setup

FastDyn is a submodule in `deps/fastdyn`. During development it points at a
local FastDyn checkout, so initialising it needs file transport allowed:

```bash
git -c protocol.file.allow=always submodule update --init deps/fastdyn
python3 -m venv .venv && . .venv/bin/activate
pip install -r deps/fastdyn/requirements.txt
pip install -e deps/fastdyn/src
pip install -e .
pytest tests
```

Running firmware needs a built FastDyn (`libfastdyn.so` and its QEMU). To use
an existing build instead of building `deps/fastdyn`, point FastDyn at it:

```bash
export FASTDYN_REPO_ROOT=/path/to/built/FastDyn
```

LibVIO is found through `pkg-config vio`; set `PKG_CONFIG_PATH` to an
installed LibVIO (1.x, model contract 1.2 or later). The tests need neither:
they use a small copy of the contract in `tests/fixtures/contract`.

## Usage

Until the `boardrunner` executable is installed (it comes with the examples),
run the command as a module. There is one command per VIOMapper stage of
the paper (Fig. 7):

```bash
python -m boardrunner trace   -c passthrough.toml -o io.trace --seconds 20 \
                              --stimulus ./type_chars.sh                    # record the hardware trace (board)
python -m boardrunner encode  -hw io.trace -b STM32F103xx -o work          # Encoder: trace -> work/out_cm
python -m boardrunner codegen -d work -p USART2 -o usart2.c --compile      # CodeGen: prompt -> LLM -> model
python -m boardrunner run -c board.toml                                     # run the firmware (FastDyn)
python -m boardrunner verify  -hw io.trace -em io.log -p USART2 \
                              -d USART2:usart2.c -b STM32F103xx -o work     # Verifier: exit 0 match, 1 mismatch
python -m boardrunner rca     -d work                                       # RCA: -> work/revised_prompt.txt
python -m boardrunner codegen -d work -o usart2.c --compile                 # next round: patch the model
```

`trace` runs the firmware with its peripherals on the real board (a
FastDyn passthrough configuration) and saves the MMIO trace; `--stimulus`
is a shell command that drives the firmware's inputs while it runs (for
example types into the board's serial port), started just before QEMU and
stopped at the end. `encode` runs once per hardware trace; then `codegen` ->
`run` -> `verify` -> `rca` repeat until `verify` reports a match.

`pipeline` does all of that automatically:

```bash
python -m boardrunner pipeline -hw io.trace -c board.toml -p USART2 -o usart2.c \
       -b STM32F103xx --seconds 15 --stimulus ./type_chars.sh -d work
```

Each round compiles the model into `--build-dir`, runs `board.toml` on
FastDyn for `--seconds` with the device of the same name (`usart2`; or
`--device USART2=NAME`) loading it, and stops when the run's trace matches
the hardware trace or after `--max-rounds` (10). Several models learned
separately and corrected together take `-m NAME:OUTPUT:PERIPH[,PERIPH]` per
model. Every round is recorded in `work/pipeline.json`; runs are in
`work/runs/round_N/`. `codegen` sends the work
directory's `revised_prompt.txt` (from `rca`) if there is one, else its
`initial_prompt.txt`, and builds the initial prompt from the encoder output
when neither exists; `codegen --prompt-only` writes the initial prompt and
stops, to read or edit it first. Several peripherals in one model take
`-p` per peripheral with `-mname` (and `-ms` for the source peripherals);
a slave model on an SPI or I2C bus takes `codegen -sm -rm REF.c -fc
FIRMWARE.c`.

Each command replaces only its own output in the work directory
(`out_cm/`, `verify/`, the prompt files); `--clean` on `encode` and
`verify` deletes the whole directory first. LLM prompts and answers are kept
in `fastdyn_llm_history/` next to it. `codegen` asks before sending a
follow-up after a failed parse, patch or compile; `--yes` retries without
asking, up to `--max-retries`.

The ablation study's variants (Table 9) are switches: `--no-encoder`
(`codegen`, `rca`), `--no-vio` (`codegen`, `rca`), `--no-rca` and
`--no-verifier` (`rca`).

`-v`, `-q`, `--log-level [LOGGER=]LEVEL` and `--log-file` work as in
FastDyn and cover both the `boardrunner.*` and `fastdyn.*` loggers. Errors
end with exit status 2. `codegen` needs `OPENAI_API_KEY` (or `--env-file`)
for OpenAI, or `--model-provider ollama`.

The prompts take the rules a model follows, the LibVIO API and the
emulator's host functions from LibVIO's model contract, found with
`pkg-config --variable=contractdir vio`; `codegen` and `rca` accept
`--contract-dir PATH` (or `$VIO_CONTRACT_DIR`) instead. Generated models use
FastDyn's model interface (`<fastdyn/device_model.h>`, ABI v2) and LibVIO v1;
`codegen --compile` builds them with FastDyn's model builder into
`--build-dir` (default `build/models`) and sends compiler errors back to
the LLM.

## Layout

```
deps/fastdyn/        FastDyn, pinned
boardrunner/
  cli.py             the boardrunner command (one subcommand per stage)
  errors.py          the errors a stage raises
  firmware.py        running firmware on FastDyn for a fixed time (trace and pipeline runs)
  hitl/              trace capture on the board (capture.py)
  viomapper/
    encoder/         context minimizer (encode.py: the stage)
    codegen/         initial prompts, LLM clients, parsing, patching, compiling
                     (prompt.py and synthesize.py: the stage)
    verifier/        trace comparison (verify.py: the stage)
    rca/             revision prompts from the Verifier's results (rca.py: the stage)
    ablations.py     the ablation study's switches
    pipeline.py      the automatic loop over the stages, and its FastDyn run step
tests/
```

Still to come: `models/` (learned models), `examples/`
(firmware and board configurations), `evaluation/`, `docs/` and `docker/`.
