"""The stage commands (encode, codegen, verify, rca) on a real trace excerpt.

tests/fixtures/f103rb_uart holds the first 600 USART2 accesses (and the 7
GPIOA accesses among them) of the NUCLEO-F103RB UART example's hardware
trace, and the GPIOA and USART part of the STM32F103xx SVD.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from boardrunner.cli import cli
from boardrunner.errors import CodegenError, VerifierError
from boardrunner.viomapper.codegen import synthesize as synthesize_module
from boardrunner.viomapper.codegen.llm.llm_client import LLMCallMetrics
from boardrunner.viomapper.codegen.synthesize import LlmSettings, synthesize
from boardrunner.viomapper.verifier import verifier

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "f103rb_uart"
TRACE = FIXTURE / "io.trace"
SVD = FIXTURE / "STM32F103xx.svd"
SVD_ARGS = ["-b", "STM32F103xx", "-s", str(SVD)]


def _run(*args):
    return CliRunner().invoke(cli, list(map(str, args)))


@pytest.fixture
def encoded(tmp_path):
    work = tmp_path / "work"
    result = _run("encode", "-hw", TRACE, *SVD_ARGS, "-o", work)
    assert result.exit_code == 0, result.output
    return work


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "usart2.c"
    path.write_text("/* USART2 model under test */\n")
    return path


def _mismatching_trace(tmp_path):
    """The hardware trace with every CR1 value zeroed: the init sequence differs."""
    path = tmp_path / "em.log"
    path.write_text(re.sub(r"(address = 0x4000440C, size = 4 bytes, value = )0x[0-9A-F]+",
                           r"\g<1>0x00000000", TRACE.read_text()))
    return path


def _verify(work, em, model):
    return _run("verify", "-hw", TRACE, "-em", em, "-d", f"USART2:{model}", "-mname", "USART2",
                "-p", "USART2", *SVD_ARGS, "-o", work)


# ── encode ───────────────────────────────────────────────────────────────────

def test_encode_replaces_only_its_own_output(encoded):
    stale = encoded / "out_cm" / "USART2" / "loop_pattern_9.txt"
    stale.write_text("from an earlier run")
    (encoded / "initial_prompt.txt").write_text("made from the earlier encoding")
    (encoded / "notes.txt").write_text("the user's")

    result = _run("encode", "-hw", TRACE, *SVD_ARGS, "-o", encoded)

    assert result.exit_code == 0, result.output
    assert (encoded / "out_cm" / "USART2" / "init.txt").is_file()
    assert not stale.exists() and not (encoded / "initial_prompt.txt").exists()
    assert (encoded / "notes.txt").read_text() == "the user's"


def test_encode_clean_wipes_the_work_dir(encoded):
    (encoded / "notes.txt").write_text("the user's")

    assert _run("encode", "-hw", TRACE, *SVD_ARGS, "-o", encoded, "--clean").exit_code == 0
    assert not (encoded / "notes.txt").exists()


def test_encode_needs_a_board_without_an_svd_file(tmp_path):
    result = _run("encode", "-hw", TRACE, "-o", tmp_path / "work")

    assert result.exit_code == 2
    assert "Error: the board is required when no SVD file is given" in result.output


# ── codegen (prompt) ─────────────────────────────────────────────────────────

def test_codegen_prompt_only_builds_the_initial_prompt(encoded):
    (encoded / "revised_prompt.txt").write_text("an earlier round's")

    result = _run("codegen", "-d", encoded, "-p", "USART2", "--prompt-only")

    assert result.exit_code == 0, result.output
    prompt = (encoded / "initial_prompt.txt").read_text()
    assert "## Peripheral Name:\nUSART2" in prompt and "fastdyn_model" in prompt
    assert not (encoded / "revised_prompt.txt").exists()


@pytest.mark.parametrize("args, message", [
    (["-p", "USART2"], "no encoder output in"),
    (["-p", "USART2", "-p", "GPIOA"], "no encoder output in"),
    ([], "the prompt needs the peripheral(s) to model"),
])
def test_codegen_says_what_the_prompt_is_missing(tmp_path, args, message):
    result = _run("codegen", "-d", tmp_path / "empty", *args, "--prompt-only")

    assert result.exit_code == 2
    assert message in result.output


def test_a_composed_model_needs_a_name(encoded):
    result = _run("codegen", "-d", encoded, "-p", "USART2", "-p", "GPIOA", "--prompt-only")

    assert result.exit_code == 2
    assert "needs a name: pass -mname" in result.output


# ── verify ───────────────────────────────────────────────────────────────────

def test_verify_exits_0_on_a_match_and_1_on_a_mismatch(tmp_path, model):
    match = _verify(tmp_path / "same", TRACE, model)
    mismatch = _verify(tmp_path / "diff", _mismatching_trace(tmp_path), model)

    assert match.exit_code == 0, match.output
    assert mismatch.exit_code == 1, mismatch.output
    saved = json.loads((tmp_path / "diff" / "verify" / "verify.json").read_text())
    assert saved["mismatches"] == {"USART2": True}
    assert saved["models"] == {"USART2": str(model)}
    assert "CR1" in saved["differences"]["USART2"]["diff_init_data"]


def test_verify_reports_an_unknown_peripheral(tmp_path, model):
    result = _run("verify", "-hw", TRACE, "-em", TRACE, "-d", f"UART4:{model}", "-p", "UART4",
                  *SVD_ARGS, "-o", tmp_path / "work")

    assert result.exit_code == 2
    assert "peripheral(s) UART4 not in the hardware trace; it has: GPIOA, USART2" in result.output


def test_verify_checks_the_model_list(tmp_path, model):
    result = _run("verify", "-hw", TRACE, "-em", TRACE, "-d", "USART2", "-p", "USART2",
                  *SVD_ARGS, "-o", tmp_path / "work")

    assert result.exit_code == 2
    assert "must be in NAME:PATH format" in result.output


def test_a_peripheral_missing_from_the_hardware_output_is_an_error(tmp_path):
    (tmp_path / "hw").mkdir()
    (tmp_path / "em").mkdir()

    with pytest.raises(VerifierError, match="USART2 is not in the hardware encoder output"):
        verifier.verify_automata(str(tmp_path / "hw"), str(tmp_path / "em"), "USART2")


# ── rca ──────────────────────────────────────────────────────────────────────

def test_rca_writes_the_revision_prompt_after_a_mismatch(tmp_path, model):
    work = tmp_path / "work"
    assert _verify(work, _mismatching_trace(tmp_path), model).exit_code == 1

    result = _run("rca", "-d", work)

    assert result.exit_code == 0, result.output
    prompt = (work / "revised_prompt.txt").read_text()
    assert "USART2 model under test" in prompt and "SEARCH" in prompt


def test_rca_full_regeneration_replaces_the_revised_prompt(tmp_path, model):
    work = tmp_path / "work"
    _verify(work, _mismatching_trace(tmp_path), model)
    _run("rca", "-d", work)

    assert _run("rca", "-d", work, "--no-rca").exit_code == 0
    assert (work / "initial_prompt.txt").is_file()
    assert not (work / "revised_prompt.txt").exists()  # codegen would otherwise prefer it


@pytest.mark.parametrize("flag, written, present, absent", [
    ("", "revised_prompt.txt", ["SEARCH", "CR1", "USART2 model under test"], []),
    # A2 for one model: the diffs and a request for a new model, without the old source
    ("--no-rca", "initial_prompt.txt", ["CR1", "## Correction Required", "fastdyn_model"],
     ["SEARCH/REPLACE blocks", "USART2 model under test"]),
    ("--no-verifier", "initial_prompt.txt", ["Current Model (Failed Verification)", "USART2 model under test"],
     ["Hardware access"]),
    ("--no-encoder", "revised_prompt.txt", ["Raw", "0x4000440C", "SEARCH"], []),
])
def test_rca_ablations(tmp_path, model, flag, written, present, absent):
    work = tmp_path / "work"
    _verify(work, _mismatching_trace(tmp_path), model)

    result = _run("rca", "-d", work, *([flag] if flag else []))

    assert result.exit_code == 0, result.output
    assert [p.name for p in work.glob("*_prompt.txt")] == [written]
    prompt = (work / written).read_text()
    for text in present:
        assert text in prompt, text
    for text in absent:
        assert text not in prompt, text


def test_rca_after_a_match_writes_nothing(tmp_path, model):
    work = tmp_path / "work"
    _verify(work, TRACE, model)

    assert _run("rca", "-d", work).exit_code == 0
    assert not list(work.glob("*_prompt.txt"))


def test_rca_needs_verification_results(tmp_path):
    (tmp_path / "work").mkdir()

    result = _run("rca", "-d", tmp_path / "work")

    assert result.exit_code == 2
    assert "run `boardrunner verify` first" in result.output


# ── codegen (LLM): retries ───────────────────────────────────────────────────

class _Client:
    """Answers with no code first, then with a model."""

    def __init__(self):
        self.calls = 0

    def send_prompt(self, prompt, stateless=True):
        self.calls += 1
        return "no code here", LLMCallMetrics(model="fake")

    def send_followup_prompt(self, **kwargs):
        self.calls += 1
        return "```c\nint model;\n```", LLMCallMetrics(model="fake")


def test_a_retry_is_asked_for_and_can_be_declined(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "initial_prompt.txt").write_text("Generate a model.")
    asked = []

    with pytest.raises(CodegenError, match="not retried"):
        synthesize(str(work), [str(tmp_path / "m.c")], client=_Client(), settings=LlmSettings(),
                   confirm_retry=lambda q: asked.append(q) or False)
    assert asked == ["Send a follow-up request to the LLM with error context?"]

    client = _Client()
    result = synthesize(str(work), [str(tmp_path / "m.c")], client=client, settings=LlmSettings(),
                        confirm_retry=None)  # --yes / the pipeline: retry without asking
    assert result.attempts == 2 and client.calls == 2
    assert "int model;" in (tmp_path / "m.c").read_text()


def test_codegen_without_a_terminal_does_not_retry(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / "initial_prompt.txt").write_text("Generate a model.")
    monkeypatch.setattr(synthesize_module, "LLMClient", lambda **kw: _Client())
    monkeypatch.setattr(synthesize_module, "load_api_key", lambda env_file: "key")

    without = _run("codegen", "-d", work, "-o", tmp_path / "m.c")
    with_yes = _run("codegen", "-d", work, "-o", tmp_path / "m.c", "--yes")

    assert without.exit_code == 2 and "pass --yes to retry" in without.output
    assert with_yes.exit_code == 0, with_yes.output


def test_codegen_says_when_prompt_options_do_not_apply(encoded, monkeypatch, caplog):
    (encoded / "initial_prompt.txt").write_text("Generate a model.")
    monkeypatch.setattr(synthesize_module, "make_client", lambda settings: SimpleNamespace())
    monkeypatch.setattr(synthesize_module, "synthesize", lambda *a, **k: None)

    result = _run("codegen", "-d", encoded, "-o", encoded / "m.c", "-p", "USART2", "--no-vio")

    assert result.exit_code == 0, result.output
    assert "Using the existing initial_prompt.txt; -p, --no-vio only apply when the prompt is built" \
        in caplog.text
