"""The ablation study's variants (paper Table 9), as switches for the stages.

* A1 ``no_encoder``: prompts carry the raw trace instead of the Encoder's output
* A2 ``no_rca``: revision prompts show the Verifier's diffs but no RCA
  analysis, and ask for a full regeneration
* A3 ``no_vio``: prompts leave out LibVIO's API and the LibVIO-only rules
* A4 ``no_verifier``: no Verifier feedback; the retry prompt is the original
  prompt, the broken model and a generic request to fix it
"""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Ablations:
    no_encoder: bool = False
    no_rca: bool = False
    no_vio: bool = False
    no_verifier: bool = False

    def active(self):
        """The names of the switched-off components, e.g. ``["no_rca"]``."""
        return [f.name for f in fields(self) if getattr(self, f.name)]


def blind_retry_prompt(original_prompt, model_source):
    """A4 for one model: the original prompt, the model that failed and a
    generic request to fix it, without any Verifier feedback."""
    return (
        original_prompt +
        "\n\n## Current Model (Failed Verification)\n"
        "The following model was generated but failed verification against the hardware trace.\n"
        "```c\n" + model_source + "\n```\n\n"
        "## Correction Required\n"
        "The model above does not correctly reproduce the hardware behavior shown in the trace data. "
        "Please analyze the hardware trace and the model source code, identify the bug, "
        "and generate a corrected model.\n"
    )
