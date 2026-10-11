"""The no-LLM end-to-end test: the VIOMapper loop on a real trace excerpt.

Only the LLM and the emulated run are scripted. Everything else is the real
code: encoding, the initial prompt, parsing and writing the model, the
Verifier, the RCA prompt and applying its SEARCH/REPLACE patch.
"""

import json
import os
import re
from pathlib import Path

import pytest

from boardrunner.viomapper.ablations import Ablations
from boardrunner.viomapper.codegen.llm.llm_client import LLMCallMetrics
from boardrunner.viomapper.codegen.prompts.contract import load_contract
from boardrunner.viomapper.codegen.synthesize import LlmSettings
from boardrunner.viomapper.encoder.encode import resolve_svd
from boardrunner.viomapper.pipeline import ModelSpec, run_pipeline

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "f103rb_uart"
TRACE = FIXTURE / "io.trace"

# The model the scripted LLM writes first: CR1 keeps only the RE and TE bits,
# so the firmware's later write of UE (0x2000) does not read back.
MODEL = """\
#include <fastdyn/device_model.h>
#include <stdlib.h>

#define CR1_WRITABLE 0x000Cu  /* RE | TE */

typedef struct {
    uint64_t base;
    uint32_t cr1;
} USART2State;

static uint64_t usart2_read(void *opaque, hwaddr addr, unsigned size, uint64_t pc) {
    USART2State *s = opaque;
    (void)size; (void)pc;
    switch (addr - s->base) {
    case 0x00: return 0xC0;     /* SR: TXE | TC */
    case 0x0C: return s->cr1;
    default: return 0;
    }
}

static void usart2_write(void *opaque, hwaddr addr, uint64_t value, unsigned size, uint64_t pc) {
    USART2State *s = opaque;
    (void)size; (void)pc;
    if (addr - s->base == 0x0C) s->cr1 = (uint32_t)value & CR1_WRITABLE;
}

static void *usart2_init(const FdDevice *dev, const char *config_json, const FdHost *host) {
    (void)config_json; (void)host;
    USART2State *s = calloc(1, sizeof(*s));
    if (s) s->base = dev->ranges[0].base;
    return s;
}

const FdModel fastdyn_model = {
    FASTDYN_MODEL_ABI_FIELDS,
    .init = usart2_init,
    .read = usart2_read,
    .write = usart2_write,
};
"""

PATCH = """\
CR1 drops UE (bit 13), so the firmware's enable write does not read back.

// FILE: usart2.c
<<<<<<< SEARCH
#define CR1_WRITABLE 0x000Cu  /* RE | TE */
=======
#define CR1_WRITABLE 0x200Cu  /* UE | RE | TE */
>>>>>>> REPLACE
"""


class ScriptedLlm:
    """Answers the initial prompt with MODEL and a revision prompt with PATCH."""

    def __init__(self):
        self.prompts = []

    def send_prompt(self, prompt, stateless=True):
        self.prompts.append(prompt)
        answer = PATCH if "<<<<<<< SEARCH" in prompt else f"```c\n{MODEL}```"
        return answer, LLMCallMetrics(model="scripted")

    def send_followup_prompt(self, **kwargs):  # pragma: no cover - the script never fails
        raise AssertionError("no retry expected")


def _trace_with_cr1(tmp_path, value):
    """The hardware trace as an emulated run would record it if every CR1
    access carried ``value``."""
    path = tmp_path / f"em_cr1_{value:x}.log"
    path.write_text(re.sub(r"(address = 0x4000440C, size = 4 bytes, value = )0x[0-9A-F]+",
                           rf"\g<1>0x{value:08X}", TRACE.read_text()))
    return path


class ScriptedRun:
    """Round 1: the run of the first model (CR1 never shows UE). Later rounds:
    a run that behaves like the hardware."""

    def __init__(self, tmp_path):
        self.first, self.requests = _trace_with_cr1(tmp_path, 0xC), []

    def __call__(self, request):
        self.requests.append(request)
        return str(self.first if request.round == 1 else TRACE)


@pytest.fixture
def setup(tmp_path):
    svd = resolve_svd("STM32F103xx", str(FIXTURE / "STM32F103xx.svd"))
    return dict(svd=svd, client=ScriptedLlm(), settings=LlmSettings(), contract=load_contract(),
                run=ScriptedRun(tmp_path), model=tmp_path / "usart2.c", work=tmp_path / "work")


def test_the_loop_corrects_the_model_until_it_matches(setup):
    llm, run, model, work = setup["client"], setup["run"], setup["model"], setup["work"]

    result = run_pipeline(TRACE, work, models=[ModelSpec("USART2", str(model), ["USART2"])],
                          svd=setup["svd"], run=run, client=llm, settings=setup["settings"],
                          contract=setup["contract"], compile=False)

    assert result.match and [r.match for r in result.rounds] == [False, True]
    assert result.rounds[0].mismatching == ["USART2"]
    # Round 1: the initial prompt, built from the encoder output and the contract.
    initial = llm.prompts[0]
    assert (work / "out_cm" / "USART2" / "init.txt").is_file()
    assert "## Peripheral Name:\nUSART2" in initial and "fastdyn_model" in initial
    # Round 2: RCA showed the model and the CR1 mismatch; its patch was applied.
    revised = llm.prompts[1]
    assert "#define CR1_WRITABLE 0x000Cu" in revised and "CR1" in revised and "<<<<<<< SEARCH" in revised
    assert "#define CR1_WRITABLE 0x200Cu" in model.read_text()
    assert [r.round for r in run.requests] == [1, 2] and run.requests[0].models == {"USART2": str(model)}
    # The record of the run.
    saved = json.loads((work / "pipeline.json").read_text())
    assert saved["match"] and [Path(r["prompts"][0]).name for r in saved["rounds"]] == \
        ["initial_prompt.txt", "revised_prompt.txt"]


def test_the_loop_stops_after_max_rounds(setup, tmp_path):
    never = _trace_with_cr1(tmp_path, 0x0)

    result = run_pipeline(TRACE, setup["work"], models=[ModelSpec("USART2", str(setup["model"]), ["USART2"])],
                          svd=setup["svd"], run=lambda request: str(never), client=setup["client"],
                          settings=setup["settings"], contract=setup["contract"], compile=False, max_rounds=2)

    assert not result.match and len(result.rounds) == 2
    assert not json.loads((setup["work"] / "pipeline.json").read_text())["match"]


def test_ablations_reach_the_prompts(setup):
    llm = setup["client"]

    run_pipeline(TRACE, setup["work"], models=[ModelSpec("USART2", str(setup["model"]), ["USART2"])],
                 svd=setup["svd"], run=setup["run"], client=llm, settings=setup["settings"],
                 contract=setup["contract"], compile=False, ablations=Ablations(no_vio=True, no_rca=True))

    initial, regenerate = llm.prompts
    assert "vio_i2c_bus_init" not in initial + regenerate  # --no-vio: no LibVIO API
    assert "<<<<<<< SEARCH" not in regenerate  # --no-rca: full regeneration, not a patch
    assert "## Correction Required" in regenerate


def _fastdyn_headers():
    root = os.environ.get("FASTDYN_REPO_ROOT")
    return root and (Path(root) / "third_party" / "common" / "qemu" / "include").is_dir()


@pytest.mark.skipif(not _fastdyn_headers(), reason="needs FASTDYN_REPO_ROOT with the QEMU headers")
def test_the_models_are_compiled_each_round(setup, tmp_path):
    build = tmp_path / "build"

    result = run_pipeline(TRACE, setup["work"], models=[ModelSpec("USART2", str(setup["model"]), ["USART2"])],
                          svd=setup["svd"], run=setup["run"], client=setup["client"],
                          settings=setup["settings"], contract=setup["contract"], compile=True,
                          build_dir=str(build))

    assert result.match
    assert (build / "usart2.so").is_file()


def test_several_models_get_their_own_first_prompt_and_a_joint_correction(setup, tmp_path):
    llm, work = setup["client"], setup["work"]
    usart, other = tmp_path / "usart2.c", tmp_path / "gpioa.c"

    result = run_pipeline(TRACE, work, models=[ModelSpec("USART2", str(usart), ["USART2"]),
                                               ModelSpec("GPIOA", str(other), ["GPIOA"])],
                          svd=setup["svd"], run=setup["run"], client=llm, settings=setup["settings"],
                          contract=setup["contract"], compile=False)

    assert result.match and len(result.rounds) == 2
    # Round 1: one initial prompt per model, each answered into its own file.
    assert [Path(p).parent.name for p in result.rounds[0].prompts] == ["work_USART2", "work_GPIOA"]
    assert other.read_text().startswith("#include <fastdyn/device_model.h>")
    # Round 2: one joint correction prompt showing both files (USART2 differs, GPIOA passes);
    # the patch went to usart2.c only.
    assert [Path(p) for p in result.rounds[1].prompts] == [work / "revised_prompt.txt"]
    assert "`usart2.c`" in llm.prompts[2] and "`gpioa.c`" in llm.prompts[2]
    assert "[MISMATCH]" in llm.prompts[2] and "[PASSING]" in llm.prompts[2]
    assert "0x200Cu" in usart.read_text() and "0x000Cu" in other.read_text()
