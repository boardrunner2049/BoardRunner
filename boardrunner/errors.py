"""Errors that stop a BoardRunner step.

Library code raises these instead of exiting; the ``boardrunner`` command
turns them into an ``Error: ...`` message and exit status 2.
"""


class BoardRunnerError(Exception):
    """A step cannot continue; the message says why and, where possible, what to do."""


class EncoderError(BoardRunnerError):
    """The trace cannot be encoded (missing trace or SVD, unknown peripheral)."""


class CodegenError(BoardRunnerError):
    """No usable prompt, or the LLM's answer cannot be turned into a model."""


class VerifierError(BoardRunnerError):
    """The traces cannot be compared (missing encoder output, bad model list)."""


class RcaError(BoardRunnerError):
    """No revision prompt can be written (no verification results, bad options)."""
