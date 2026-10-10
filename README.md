# BoardRunner

BoardRunner rehosts embedded firmware automatically. It observes the firmware
running on the real board (hardware in the loop), learns a model of each
peripheral from that trace (VIOMapper: Encoder, CodeGen, Verifier, RCA), and
then runs the firmware without the board, on [FastDyn](deps/fastdyn) with the
learned models and [LibVIO](https://github.com/PSecLab/LibVIO).

> **Status:** BoardRunner is being moved out of the FastDyn repository into
> this one. The VIOMapper code and the `boardrunner` command are here; the
> trace capture, examples and evaluation follow.

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
installed LibVIO.

## Usage

Until the `boardrunner` executable is installed (it comes with the examples),
run the command as a module:

```bash
python -m boardrunner --help
python -m boardrunner generate ...       # build the LLM prompt from a hardware trace
python -m boardrunner llm -d WORK -o model.c   # send it and write or patch the model
python -m boardrunner verifier ...       # compare the model with the hardware trace
python -m boardrunner build-models ...   # FastDyn's model builder
python -m boardrunner run -c board.toml  # FastDyn's runner
```

`-v`, `-q`, `--log-level [LOGGER=]LEVEL` and `--log-file` work as in
FastDyn and cover both the `boardrunner.*` and `fastdyn.*` loggers. The
`llm` command needs `OPENAI_API_KEY` (or `--env-file`) for OpenAI, or
`--model-provider ollama`. The command names are the ones FastDyn used; they
change to the VIOMapper stages later.

## Layout

```
deps/fastdyn/        FastDyn, pinned
boardrunner/
  cli.py             the boardrunner command
  hitl/              trace capture on the board through FastDyn
  viomapper/
    encoder/         context minimizer (trace -> per-peripheral context)
    codegen/         prompts/, llm/ clients, response parsing, patching, compiling
    verifier/        model verification against the trace (still includes RCA)
    rca/             RCA, once it is split out of verifier/
tests/
```

Still to come: trace capture, `models/` (learned models), `examples/`
(firmware and board configurations), `evaluation/`, `docs/` and `docker/`.
