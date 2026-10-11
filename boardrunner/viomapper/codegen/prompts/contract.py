"""The LibVIO model contract, as text for LLM prompts.

LibVIO installs the rules a device model follows (``model_rules.md``), its
API (``api_summary.md``, one line per function) and the emulator's host
functions (``host_api.md``). The prompts take these from the contract instead of
keeping their own copies, so they always describe the LibVIO and FastDyn
the models are built against.

The contract directory is, in this order: the one passed in, ``$VIO_CONTRACT_DIR``,
or ``pkg-config --variable=contractdir vio``.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from boardrunner.errors import BoardRunnerError

CONTRACT_DIR_ENV = "VIO_CONTRACT_DIR"

# The contract versions these prompts are written for: the VIO and audience
# markers came in 1.2.0.
SUPPORTED_MAJOR = 1
MIN_MINOR = 2

AUDIENCES = ("model", "slave", "host")

_VIO_BLOCK = re.compile(r"<!-- vio -->.*?<!-- /vio -->", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_AUDIENCE = re.compile(r"^<!-- for: (\w+) -->$", re.MULTILINE)


class ContractError(BoardRunnerError):
    """The contract cannot be found or read, or is not one these prompts support."""


def find_contract_dir(directory=None):
    """Return the contract directory (see the module docstring)."""
    if directory:
        return Path(directory)
    if os.environ.get(CONTRACT_DIR_ENV):
        return Path(os.environ[CONTRACT_DIR_ENV])
    if shutil.which("pkg-config") is None:
        raise ContractError(
            f"cannot find the LibVIO model contract: set {CONTRACT_DIR_ENV}, or install "
            "pkg-config and LibVIO")
    result = subprocess.run(["pkg-config", "--variable=contractdir", "vio"],
                            capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise ContractError(
            f"cannot find the LibVIO model contract: set {CONTRACT_DIR_ENV}, or put an "
            "installed LibVIO on PKG_CONFIG_PATH (pkg-config vio)")
    return Path(result.stdout.strip())


def _read(directory, name):
    path = directory / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise ContractError(f"cannot read the LibVIO model contract: {e}") from e


def _shift_headings(text, levels):
    """Demote Markdown headings by ``levels``, so the contract nests under the
    prompt's own sections. Lines inside code blocks are left alone."""
    lines, in_code = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and line.startswith("#"):
            line = "#" * levels + line
        lines.append(line)
    return "\n".join(lines)


def _vio(text, vio):
    """Keep (``vio``) or drop the text between ``<!-- vio -->`` and ``<!-- /vio -->``."""
    if vio:
        return text.replace("<!-- vio -->", "").replace("<!-- /vio -->", "")
    return _VIO_BLOCK.sub("", text)


def _tidy(text):
    """Drop the remaining HTML comments and collapse the blank lines they leave."""
    text = _COMMENT.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@dataclass(frozen=True)
class Contract:
    directory: Path
    version: str
    model_rules_md: str
    api_summary_md: str
    host_api_md: str

    def rules(self, vio=True):
        """The device model rules, as a ``##`` section; ``vio=False`` drops the
        LibVIO-only text."""
        return _shift_headings(_tidy(_vio(self.model_rules_md, vio)), 1)

    def _api_sections(self):
        """(preamble, [(audience, text), ...]) of api_summary.md."""
        parts = re.split(r"^(?=## )", self.api_summary_md, flags=re.MULTILINE)
        sections = []
        for part in parts[1:]:
            match = _AUDIENCE.search(part)
            if not match or match.group(1) not in AUDIENCES:
                raise ContractError(
                    f"{self.directory / 'api_summary.md'}: section "
                    f"{part.splitlines()[0]!r} has no audience (<!-- for: ... -->)")
            sections.append((match.group(1), part))
        return parts[0], sections

    def api(self, audiences=("model",), vio=True):
        """The functions a model may call, as ``###`` sections: the emulator's
        host functions and, with ``vio``, the LibVIO sections for ``audiences``."""
        parts = [_vio(self.host_api_md, vio)]
        if vio:
            preamble, sections = self._api_sections()
            parts.append(preamble)
            parts += [text for audience, text in sections if audience in audiences]
        return _shift_headings(_tidy("\n\n".join(parts)), 2)


@lru_cache(maxsize=None)
def _load(directory):
    if not directory.is_dir():
        raise ContractError(f"the LibVIO model contract directory does not exist: {directory}")
    version = _read(directory, "VERSION").strip()
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ContractError(f"{directory / 'VERSION'}: not a version: {version!r}")
    major, minor = int(match.group(1)), int(match.group(2))
    if major != SUPPORTED_MAJOR or minor < MIN_MINOR:
        raise ContractError(
            f"the LibVIO model contract in {directory} is version {version}; these prompts "
            f"need {SUPPORTED_MAJOR}.{MIN_MINOR} or a later {SUPPORTED_MAJOR}.x")
    contract = Contract(
        directory=directory,
        version=version,
        model_rules_md=_read(directory, "model_rules.md"),
        api_summary_md=_read(directory, "api_summary.md"),
        host_api_md=_read(directory, "host_api.md"),
    )
    contract._api_sections()  # fail now on a malformed reference
    return contract


def load_contract(directory=None):
    """Load the contract from ``directory``, ``$VIO_CONTRACT_DIR`` or pkg-config."""
    return _load(find_contract_dir(directory).resolve())
