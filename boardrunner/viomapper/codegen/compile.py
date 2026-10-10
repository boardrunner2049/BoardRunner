"""
Compiles generated device models with FastDyn's model builder
(``fastdyn.build_models``) and formats compiler errors for an LLM follow-up
prompt.
"""

import logging
from pathlib import Path

from fastdyn import build_models
from fastdyn.model_build import FAILED, ModelBuildError


log = logging.getLogger(__name__)


class CompilationError(Exception):
    """Raised when models cannot be compiled at all (no compiler, missing
    headers, bad sources), as opposed to compiler errors in a model."""


def compile_models(sources, build_dir):
    """Build each model source into ``build_dir/<name>.so``.

    Args:
        sources: Paths of the model ``.c`` files.
        build_dir: Directory for the shared libraries.

    Returns:
        Tuple of (success: bool, compiler_output: str); the output holds the
        diagnostics of the models that failed.

    Raises:
        CompilationError: If nothing can be built.
    """
    try:
        report = build_models([Path(s) for s in sources], build_dir, keep_going=True)
    except ModelBuildError as e:
        raise CompilationError(str(e)) from e

    for result in report.results:
        if result.status == FAILED:
            log.error("Model %s failed to compile", result.name)
        else:
            log.info("Model %s: %s -> %s", result.name, result.status, result.output)
    output = "\n".join(r.diagnostics for r in report.results if r.status == FAILED and r.diagnostics)
    return report.ok, output


def format_compilation_error(compiler_output: str) -> str:
    """Format compiler output into a string suitable for an LLM follow-up prompt.

    Extracts error lines and provides context for the LLM to fix.

    Args:
        compiler_output: Raw stdout/stderr from the build process.

    Returns:
        Formatted error description string.
    """
    # Extract lines containing "error:" for a focused summary
    lines = compiler_output.split("\n")
    error_lines = [
        line for line in lines
        if "error:" in line.lower() or "undefined reference" in line.lower()
    ]

    summary = "\n".join(error_lines) if error_lines else compiler_output

    return (
        "Compilation Error:\n"
        "The model failed to compile with the following error(s):\n\n"
        "%s\n\n"
        "Full compiler output:\n%s"
        % (summary, compiler_output[-3000:])  # Limit to last 3000 chars
    )
