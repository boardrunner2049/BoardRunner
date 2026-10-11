"""CodeGen stage, LLM half: send the prompt, write or patch the model, compile.

The prompt is the work directory's ``revised_prompt.txt`` (from RCA: the LLM
answers with SEARCH/REPLACE patches for the existing model files) or else its
``initial_prompt.txt`` (the LLM answers with the full model source). Every
prompt and response is also kept in ``fastdyn_llm_history/`` next to the
work directory.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional

from boardrunner.errors import CodegenError
from boardrunner.viomapper.codegen.llm.handlers import (
    handle_compilation,
    handle_initial_prompt,
    handle_revised_prompt,
    llm_history_next,
)
from boardrunner.viomapper.codegen.llm.llm_client import LLMClient, LLMClientError, load_api_key

log = logging.getLogger(__name__)

INITIAL_PROMPT = "initial_prompt.txt"
REVISED_PROMPT = "revised_prompt.txt"
HISTORY_DIR = "fastdyn_llm_history"


@dataclass
class LlmSettings:
    """Which LLM to ask and how."""

    model: str = "gpt-4o"
    provider: str = "openai"
    env_file: str = "~/.fastdyn.env"
    temperature: Optional[float] = None  # None: 0.2 for OpenAI, 0.1 for Ollama
    reasoning_effort: Optional[str] = None
    stateless: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_num_ctx: int = 262144
    ollama_timeout: float = 1800.0


@dataclass
class SynthesisResult:
    prompt_path: str
    prompt_type: str  # "initial" or "revised"
    attempts: int
    history_prefix: str


def make_client(settings):
    """Create the LLM client for ``settings``."""
    provider = settings.provider.lower()
    try:
        if provider == "ollama":
            from boardrunner.viomapper.codegen.llm.ollama_client import OllamaClient

            if settings.reasoning_effort and settings.reasoning_effort != "none":
                log.warning(
                    "--reasoning-effort is ignored for --model-provider ollama. "
                    "Use Ollama model configuration for reasoning controls."
                )
            return OllamaClient(
                model=settings.model,
                base_url=settings.ollama_url,
                temperature=0.1 if settings.temperature is None else settings.temperature,
                num_ctx=settings.ollama_num_ctx or None,
                timeout=settings.ollama_timeout,
            )
        return LLMClient(
            api_key=load_api_key(settings.env_file),
            model=settings.model,
            temperature=0.2 if settings.temperature is None else settings.temperature,
            reasoning_effort=settings.reasoning_effort,
        )
    except LLMClientError as e:
        raise CodegenError(str(e)) from e


def select_prompt(work_dir):
    """Return ``(path, type)`` of the prompt to send, or None if there is none."""
    revised = os.path.join(work_dir, REVISED_PROMPT)
    initial = os.path.join(work_dir, INITIAL_PROMPT)
    if os.path.isfile(revised):
        return revised, "revised"
    if os.path.isfile(initial):
        return initial, "initial"
    return None


def synthesize(work_dir, outputs, *, client, settings, compile=False, build_dir="build/models",
               max_retries=1, evaluate=False,
               confirm_retry: Optional[Callable[[str], bool]] = None):
    """Send the work directory's prompt and write or patch ``outputs``.

    A failed parse, patch or compile is sent back to the LLM up to
    ``max_retries`` times. ``confirm_retry(question)`` is asked before each
    retry; None retries without asking.
    """
    selected = select_prompt(work_dir)
    if selected is None:
        raise CodegenError(f"no prompt in {work_dir}: expected {INITIAL_PROMPT} or {REVISED_PROMPT}")
    prompt_path, prompt_type = selected
    log.info("Found %s -- using %s", os.path.basename(prompt_path),
             "SEARCH/REPLACE patch mode" if prompt_type == "revised" else "full code extraction mode")

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()
    if not prompt_text.strip():
        raise CodegenError(f"the prompt file is empty: {prompt_path}")
    log.info("Read prompt from %s (%d characters)", prompt_path, len(prompt_text))

    if prompt_type == "revised":
        missing = [p for p in outputs if not os.path.isfile(p)]
        if missing:
            raise CodegenError("a revised prompt patches existing model files; not found: " + ", ".join(missing))

    # -- Persistent LLM history -----------------------------------------------
    # Saved in fastdyn_llm_history/ next to the work directory, never deleted.
    # Each invocation gets a new NNN prefix; retries within the same run get
    # separate response files (NNN_response_1.txt, NNN_response_2.txt, ...).
    history_dir = os.path.join(os.path.dirname(os.path.abspath(work_dir)), HISTORY_DIR)
    history_iter = llm_history_next(history_dir)
    history_prefix = os.path.join(history_dir, f"{history_iter:03d}")
    with open(f"{history_prefix}_prompt.txt", "w", encoding="utf-8") as f:
        f.write(prompt_text)
    log.info("LLM history prompt saved to %s_prompt.txt (iteration %d)", history_prefix, history_iter)

    metrics_path = os.path.join(history_dir, "metrics.jsonl") if evaluate else None
    if metrics_path:
        log.info("Evaluation mode enabled. Metrics will be written to %s", metrics_path)

    def write_metrics(metrics, attempt_num, call_type, extra=None):
        if not metrics_path or metrics is None:
            return
        entry = metrics.to_dict()
        entry["iteration"] = history_iter
        entry["attempt"] = attempt_num
        entry["type"] = call_type
        entry["model_provider"] = settings.provider.lower()
        entry["reasoning_effort"] = settings.reasoning_effort
        if extra:
            entry.update(extra)
        with open(metrics_path, "a", encoding="utf-8") as mf:
            mf.write(json.dumps(entry) + "\n")

    def may_retry(attempt, question):
        if attempt >= max_attempts:
            raise CodegenError(f"all {max_attempts} attempt(s) failed")
        if confirm_retry is not None and not confirm_retry(question):
            raise CodegenError("stopped: not retried")

    # -- Send prompt and process response -------------------------------------
    max_attempts = 1 + max_retries
    previous_response = None
    error_context = ""
    for attempt in range(1, max_attempts + 1):
        is_retry = attempt > 1
        call_type = "followup" if is_retry else ("revision" if prompt_type == "revised" else "initial")
        try:
            if is_retry and previous_response:
                log.info("Retry attempt %d/%d...", attempt - 1, max_retries)
                response_text, call_metrics = client.send_followup_prompt(
                    original_prompt=prompt_text,
                    previous_response=previous_response,
                    error_context=error_context,
                    stateless=settings.stateless,
                )
            else:
                response_text, call_metrics = client.send_prompt(prompt_text, stateless=settings.stateless)
        except LLMClientError as e:
            raise CodegenError(f"LLM request failed: {e}") from e

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

        if prompt_type == "initial":
            success, error_context = handle_initial_prompt(response_text, outputs[0], work_dir)
        else:
            success, error_context = handle_revised_prompt(response_text, outputs, work_dir)
        if not success:
            write_metrics(call_metrics, attempt, call_type, {"result": "parse_fail"})
            may_retry(attempt, "Send a follow-up request to the LLM with error context?")
            continue

        if compile:
            compile_success, compile_error, is_setup_error = handle_compilation(outputs, build_dir)
            if not compile_success:
                write_metrics(call_metrics, attempt, call_type, {"result": "compile_fail"})
                if is_setup_error:
                    raise CodegenError(f"models cannot be compiled: {compile_error}")
                error_context = compile_error
                may_retry(attempt, "Compilation failed. Send a follow-up request to the LLM?")
                continue

        write_metrics(call_metrics, attempt, call_type, {"result": "success"})
        log.info("LLM processing completed successfully.")
        return SynthesisResult(prompt_path, prompt_type, attempt, history_prefix)
    raise CodegenError(f"all {max_attempts} attempt(s) failed")  # not reached
